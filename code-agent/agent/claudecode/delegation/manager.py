"""子 Agent 委派系统 - Delegation / Orchestration

复现 Claude Code 的子 Agent 委派机制：
- 主 Agent 可以将复杂任务委派给专用子 Agent
- 子 Agent 在独立沙箱中执行，结果汇总返回给主 Agent
- 支持多种类型：代码分析、测试执行、文件浏览、安全审查等

架构：
  ┌─────────────────────────────────────────────┐
  │  ClaudeCode Agent (主 Agent)                 │
  │  ┌─ delegate_to_sub_agent 工具 ───────────┐ │
  │  │   task: "分析这个 bug 的原因"            │ │
  │  │   agent_type: code_analysis             │ │
  │  │   files: [astropy/modeling/separable.py]│ │
  │  └──────────────────────────────────────────┘ │
  │         ↓ (调用)                               │
  │  ┌────────────────────────────────────────┐  │
  │  │  SubAgent (子 Agent)                    │  │
  │  │  - 有独立的 prompt + tools              │  │
  │  │  - 有独立的 token 预算                  │  │
  │  │  - 返回结构化结果给主 Agent             │  │
  │  └────────────────────────────────────────┘  │
  └──────────────────────────────────────────────┘
"""
import json
import time
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Callable
from enum import Enum

from langchain.agents import AgentExecutor, create_react_agent
from langchain.prompts import PromptTemplate
from langchain.tools import Tool
from langchain_core.runnables import RunnableConfig

from llm.config import LLMConfig, PROVIDER_BASE_URLS, DEFAULT_LLM_CONFIG
from utils.logger import get_logger

logger = get_logger()


class SubAgentType(str, Enum):
    """子 Agent 类型"""
    CODE_ANALYSIS = "code_analysis"     # 代码分析专家
    TEST_EXECUTOR = "test_executor"       # 测试执行专家
    FILE_BROWSER = "file_browser"         # 文件浏览专家
    SAFETY_REVIEWER = "safety_reviewer"   # 安全审查专家
    DOCUMENTATION = "documentation"       # 文档编写专家
    SEARCH_EXPERT = "search_expert"       # 搜索/检索专家


@dataclass
class SubAgentResult:
    """子 Agent 执行结果"""
    agent_type: str
    task: str
    output: str
    steps: List[Dict] = field(default_factory=list)
    token_used: int = 0
    success: bool = True
    error_message: str = ""

    def to_text(self) -> str:
        """转换为文本，供主 Agent 继续处理"""
        lines = [
            f"=== Sub Agent [{self.agent_type}] 执行结果 ===",
            f"任务: {self.task[:200]}",
            f"状态: {'成功' if self.success else '失败'}",
            f"使用 tokens: {self.token_used}",
            "",
            "详细输出:",
            self.output,
        ]
        if self.error_message:
            lines.append(f"\n错误信息: {self.error_message}")
        return "\n".join(lines)


class TokenBudgetExceeded(Exception):
    """子 Agent token 预算耗尽"""
    pass


class SubAgent:
    """专用子 Agent

    每个子 Agent 有:
    - 专门定制的系统 prompt
    - 精简的工具集（减少工具选择噪声）
    - 独立的 token 预算
    - 执行结果以结构化方式返回给主 Agent
    """

    def __init__(
        self,
        agent_type: str,
        config: LLMConfig,
        tools: List[Tool],
        system_prompt: str,
        max_iterations: int = 10,
        token_budget: int = 8000,
        working_dir: Optional[str] = None,
    ):
        self.agent_type = agent_type
        self.config = config
        self.tools = tools
        self.system_prompt = system_prompt
        self.max_iterations = max_iterations
        self.token_budget = token_budget
        self.working_dir = working_dir
        self.token_used = 0
        self.steps: List[Dict] = []
        self.executor: Optional[AgentExecutor] = None
        self._build()

    def _build(self):
        """构建 LangChain Agent"""
        # 注意：这里不能用 f-string，否则本地变量 tool_names 会被 Python 提前替换，
        # 导致 PromptTemplate 看不到 {tool_names} 变量，抛出 "missing required variables"。
        prompt = PromptTemplate.from_template("""
{system_prompt}

You are a specialist sub-agent focused on a narrow sub-task.
You have your own tool-set and token budget. Complete your sub-task efficiently.

AVAILABLE TOOLS:
{tools}

INSTRUCTIONS: Strictly follow this ReAct format.

Thought: Your reasoning - analyze the task and decide the next step.
Action: The tool name, MUST be one of [{tool_names}].
Action Input: The input for the selected tool.
Observation: The tool result.

(The Thought/Action/Action Input/Observation cycle can repeat.)

When ready:
Thought: I have gathered enough information.
Final Answer: The complete, structured final answer.

RULES:
- Only use provided tools.
- Output MUST be in English.
- Stay concise and focused on your sub-task.
- Finish with a clear structured answer.

Begin!

Question: {input}
Thought:{agent_scratchpad}
""")
        # 把 system_prompt 注入到 PromptTemplate 的 input_variables 中（通过 partial_variables）
        # 简化：直接用 partial
        prompt = prompt.partial(system_prompt=self.system_prompt or "")

        # 使用简单的 LLM（不做复杂重试）
        try:
            from langchain_openai import ChatOpenAI
            base_url = self.config.base_url or PROVIDER_BASE_URLS.get(
                self.config.provider, PROVIDER_BASE_URLS['openai']
            )
            llm = ChatOpenAI(
                api_key=self.config.api_key,
                base_url=base_url,
                model=self.config.model,
                temperature=self.config.temperature,
                max_tokens=4096,
                timeout=120,
                disable_streaming=True,
            )

            agent = create_react_agent(llm=llm, tools=self.tools, prompt=prompt)
            self.executor = AgentExecutor(
                agent=agent,
                tools=self.tools,
                verbose=True,                      # 打印子 Agent 的 Thought/Action/Observation
                max_iterations=self.max_iterations,
                handle_parsing_errors=True,
                return_intermediate_steps=True,    # 保留中间步骤，返回给主 Agent
            )
        except Exception as e:
            logger.warning(f"子 Agent [{self.agent_type}] 构建失败: {e}")
            self.executor = None

    def run(self, task: str) -> SubAgentResult:
        """执行子任务"""
        budget_left = self.token_budget - self.token_used

        if self.executor is None:
            return SubAgentResult(
                agent_type=self.agent_type,
                task=task,
                output="子 Agent 未能初始化，请检查配置",
                success=False,
                error_message="executor is None"
            )

        start_time = time.time()
        try:
            result = self.executor.invoke({
                'input': task,
                'token_budget_left': f"{budget_left} tokens",
            })

            elapsed = time.time() - start_time
            output = str(result.get('output', ''))

            self.token_used += int(len(output) / 4)  # 粗略估算

            logger.info(
                f"子 Agent [{self.agent_type}] 完成 - 用时 {elapsed:.1f}s, "
                f"估算 token 使用: {self.token_used}"
            )

            # 把子 Agent 的中间步骤一并返回（方便主 Agent trace 查看）
            steps = []
            raw_steps = result.get('intermediate_steps', []) or []
            for i, step in enumerate(raw_steps):
                try:
                    if isinstance(step, (tuple, list)) and len(step) >= 2:
                        action, obs = step[0], step[1]
                        steps.append({
                            "step": i + 1,
                            "tool": str(getattr(action, 'tool', '')),
                            "tool_input": str(getattr(action, 'tool_input', ''))[:1500],
                            "thought": str(getattr(action, 'log', ''))[:1500],
                            "observation": str(obs)[:1500],
                        })
                except Exception:
                    pass

            return SubAgentResult(
                agent_type=self.agent_type,
                task=task,
                output=output,
                steps=steps,
                token_used=self.token_used,
                success=True
            )

        except Exception as e:
            logger.error(f"子 Agent [{self.agent_type}] 执行失败: {e}")
            return SubAgentResult(
                agent_type=self.agent_type,
                task=task,
                output=f"子 Agent 执行失败: {e}",
                success=False,
                error_message=str(e)
            )


# ============================================================
# 子 Agent Prompt 模板库
# ============================================================

SUB_AGENT_PROMPTS = {
    SubAgentType.CODE_ANALYSIS: """你是一位资深代码分析专家。
你的任务是：阅读指定文件，分析代码逻辑、数据流、潜在 bug，并给出专业的代码审查意见。

请特别关注：
1. 函数调用链和依赖关系
2. 可能的边界条件和异常处理
3. 与问题描述相关的具体代码段
4. 给出修复建议的思路（不要直接写 patch）

请用结构化格式报告你的发现。""",

    SubAgentType.TEST_EXECUTOR: """你是一位测试执行专家。
你的任务是：在安全的环境中运行测试，并报告测试结果。
你有 write 和 bash 权限，但请保持最小操作原则。

请在报告中列出：
1. 运行了哪些测试
2. 通过/失败数量
3. 失败测试的详细错误信息
4. 如何复现这些失败""",

    SubAgentType.FILE_BROWSER: """你是一位文件浏览专家。
你的任务是：在代码库中快速定位相关文件和代码。

请提供：
1. 相关文件的完整路径
2. 关键代码片段（带行号）
3. 文件之间的关联关系""",

    SubAgentType.SAFETY_REVIEWER: """你是一位安全审查专家。
你的任务是：审查代码变更的安全性。

请检查：
1. 是否引入了新的安全漏洞（SQL injection, XSS, RCE 等）
2. 是否修改了敏感配置文件
3. 是否有硬编码的密钥或 token
4. 数据验证是否充分""",

    SubAgentType.DOCUMENTATION: """你是一位文档编写专家。
你的任务是：为代码编写清晰、专业的文档。

请提供：
1. 函数/类 docstring
2. 使用示例
3. 关键设计决策说明""",

    SubAgentType.SEARCH_EXPERT: """你是一位代码搜索专家。
你的任务是：在代码库中执行高效的搜索。

请使用 grep/find 等工具，找到：
1. 特定符号的定义位置
2. 特定符号的调用位置
3. 相关的测试文件""",
}


class DelegationManager:
    """委派管理器 - 供主 Agent 调用的工具集合

    主 Agent 不需要自己管理子 Agent，只需要通过 delegate_to_sub_agent 工具
    指定 agent_type 和 task，即可触发子 Agent 执行。
    """

    def __init__(
        self,
        config: LLMConfig,
        tools_for_sub: Dict[str, List[Tool]],
        working_dir: Optional[str] = None,
    ):
        """
        Args:
            config: 全局 LLM 配置
            tools_for_sub: 每种类型子 Agent 使用的工具集
            working_dir: 工作目录
        """
        self.config = config
        self.tools_for_sub = tools_for_sub
        self.working_dir = working_dir
        self.sub_agents: Dict[str, SubAgent] = {}
        self.delegation_history: List[Dict] = []

    def delegate(self, args_str: str) -> str:
        """委派任务给子 Agent

        输入格式: agent_type|task_description
        例: code_analysis|分析 astropy/modeling/separable.py 中的 separability_matrix 函数

        或 JSON 格式: {"agent_type": "code_analysis", "task": "..."}
        """
        # 解析输入
        args_str = args_str.strip().strip('"').strip("'")

        # 先尝试 JSON 解析
        agent_type, task = self._parse_args(args_str)

        if agent_type not in SUB_AGENT_PROMPTS:
            available = ", ".join(SUB_AGENT_PROMPTS.keys())
            return f"[Delegation] 未知的子 Agent 类型: {agent_type}. 可用: {available}"

        tools = self.tools_for_sub.get(agent_type, [])
        if not tools:
            return f"[Delegation] 子 Agent [{agent_type}] 没有可用工具"

        # 创建或复用子 Agent
        if agent_type not in self.sub_agents:
            self.sub_agents[agent_type] = SubAgent(
                agent_type=agent_type,
                config=self.config,
                tools=tools,
                system_prompt=SUB_AGENT_PROMPTS[SubAgentType(agent_type)],
                working_dir=self.working_dir
            )

        logger.info(f"[Delegation] 委派任务给 [{agent_type}]: {task[:80]}...")

        # 执行
        result = self.sub_agents[agent_type].run(task)

        self.delegation_history.append({
            "agent_type": agent_type,
            "task": task,
            "success": result.success,
            "token_used": result.token_used,
        })

        return result.to_text()

    def _parse_args(self, args_str: str):
        """解析输入参数"""
        # JSON 格式
        if args_str.startswith('{'):
            try:
                data = json.loads(args_str)
                return data.get('agent_type', ''), data.get('task', '')
            except Exception:
                pass

        # | 分隔格式
        if '|' in args_str:
            parts = args_str.split('|', 1)
            return parts[0].strip(), parts[1].strip()

        # 默认：整个字符串作为 task，使用 code_analysis
        return SubAgentType.CODE_ANALYSIS.value, args_str

    def get_langchain_tool(self) -> Tool:
        """将委派功能作为工具暴露给主 Agent"""
        available_types = ", ".join(
            f"'{k}'" for k in SUB_AGENT_PROMPTS.keys()
        )
        return Tool(
            name="delegate_to_sub_agent",
            description=(
                "Delegate a specialized sub-task to a specialist sub-agent. "
                "Use this when you need deep expertise on a specific topic. "
                f"Available agent types: {available_types}. "
                "INPUT FORMAT: 'agent_type|task_description' "
                "EXAMPLE: 'code_analysis|分析这个文件中 xxx 函数的逻辑' "
                "EXAMPLE: 'search_expert|在项目中搜索 separability_matrix 的定义和使用'"
            ),
            func=self.delegate,
        )

    def summary(self) -> dict:
        """获取委派历史摘要"""
        return {
            "total_delegations": len(self.delegation_history),
            "success_rate": sum(1 for h in self.delegation_history if h["success"]) / max(len(self.delegation_history), 1),
            "total_tokens": sum(h["token_used"] for h in self.delegation_history),
            "agents_used": list(set(h["agent_type"] for h in self.delegation_history)),
        }
