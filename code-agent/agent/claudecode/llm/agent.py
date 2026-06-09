"""ClaudeCode Agent - 带安全审查 + 子 Agent 委派的主 Agent

核心架构：
- 基于 LangChain ReAct Agent 框架
- 工具调用前经过 SafetyGuard 审查（高风险操作暂停并确认）
- 可通过 delegate_to_sub_agent 工具委派任务给专家子 Agent
- 增强的 prompt 明确告知 Agent 它有这些"高级能力"
"""
import time
from typing import List, Optional, Dict, Any

from langchain.agents import AgentExecutor, create_react_agent
from langchain.prompts import PromptTemplate
from langchain.tools import Tool
from langchain_openai import ChatOpenAI
from langchain_core.runnables import RunnableConfig

from llm.config import LLMConfig, PROVIDER_BASE_URLS, DEFAULT_LLM_CONFIG
from safety.guard import SafetyGuard, ConfirmationMode
from delegation.manager import DelegationManager, SubAgentType
from tools.factory import (
    create_bash_tool,
    create_view_file_tool,
    create_edit_file_tool,
)
from utils.logger import get_logger

logger = get_logger()


class ClaudeCodeAgent:
    """Claude Code 风格 Agent - 主 Agent

    特性：
    1. 安全审查：每次调用工具前检查风险
    2. 子 Agent 委派：可以将复杂任务委派给专家子 Agent
    3. 生产级 prompt：明确告知 Agent 拥有高级能力
    """

    def __init__(
        self,
        config: Optional[LLMConfig] = None,
        working_dir: Optional[str] = None,
        confirm_mode: ConfirmationMode = ConfirmationMode.INTERACTIVE,
        enable_delegation: bool = True,
        on_risk_callback: Optional[callable] = None,
    ):
        self.config = config or DEFAULT_LLM_CONFIG
        self.working_dir = working_dir
        self.enable_delegation = enable_delegation
        self.tools: List[Tool] = []

        # 初始化安全审查器
        self.safety_guard = SafetyGuard(
            confirm_mode=confirm_mode,
            working_dir=working_dir,
            on_risk_callback=on_risk_callback,
        )

        # 初始化委派管理器
        self.delegation_manager: Optional[DelegationManager] = None

        # 构建 Agent
        self.executor: Optional[AgentExecutor] = None
        self._build()

    # ============================================================
    # 构建
    # ============================================================

    def _build(self):
        """创建 LLM + 注册工具 + 构建 Agent"""
        # 1. 创建 LLM
        base_url = self.config.base_url or PROVIDER_BASE_URLS.get(
            self.config.provider, PROVIDER_BASE_URLS['openai']
        )
        self.llm = ChatOpenAI(
            api_key=self.config.api_key,
            base_url=base_url,
            model=self.config.model,
            temperature=self.config.temperature,
            max_tokens=8192,
            timeout=120,
            disable_streaming=True,
        )

        # 2. 注册基础工具（带安全审查）
        if self.working_dir:
            self.tools.append(create_bash_tool(self.working_dir, self.safety_guard))
            self.tools.append(create_view_file_tool(self.working_dir))
            self.tools.append(create_edit_file_tool(self.working_dir, self.safety_guard))

            # 3. 注册子 Agent 委派工具（如启用）
            if self.enable_delegation:
                # 为各类子 Agent 准备精简工具集
                read_only_tools = [
                    create_bash_tool(self.working_dir, SafetyGuard(
                        confirm_mode=ConfirmationMode.AUTO_DENY
                    ), timeout=30),
                    create_view_file_tool(self.working_dir),
                ]

                self.delegation_manager = DelegationManager(
                    config=self.config,
                    tools_for_sub={
                        SubAgentType.CODE_ANALYSIS.value: read_only_tools,
                        SubAgentType.FILE_BROWSER.value: read_only_tools,
                        SubAgentType.SEARCH_EXPERT.value: read_only_tools,
                        SubAgentType.SAFETY_REVIEWER.value: read_only_tools,
                        SubAgentType.DOCUMENTATION.value: read_only_tools,
                        SubAgentType.TEST_EXECUTOR.value: [
                            create_bash_tool(self.working_dir, self.safety_guard, timeout=120),
                            create_view_file_tool(self.working_dir),
                        ],
                    },
                    working_dir=self.working_dir,
                )
                self.tools.append(self.delegation_manager.get_langchain_tool())

        # 4. 构建 Agent Executor
        if self.tools:
            self._build_executor()

        logger.info(
            f"ClaudeCode Agent 初始化完成 - Model: {self.config.model}, "
            f"工具: {len(self.tools)}个, 委派: {'启用' if self.enable_delegation else '禁用'}"
        )

    def _build_executor(self):
        """构建 LangChain ReAct Agent 执行器"""
        # Claude Code 风格 prompt - 使用 PromptTemplate 的变量（不要用 f-string，否则本地变量会被提前替换）
        prompt = PromptTemplate.from_template("""
You are Claude Code - a powerful AI code assistant.
You have the following advanced capabilities:

1. **Tool Calling**: Use the available tools to accomplish your task.
2. **Safety Guard**: High-risk operations (rm -rf, sudo, overwrite system files,
   etc.) are automatically paused and require user confirmation. File edits are
   also reviewed.
3. **Sub-Agent Delegation**: For complex sub-tasks, delegate to specialist
   sub-agents via the `delegate_to_sub_agent` tool.
   Available agent types: code_analysis, test_executor, file_browser,
   safety_reviewer, documentation, search_expert.

AVAILABLE TOOLS:
{tools}

---
INSTRUCTIONS: Strictly follow this ReAct format.

Thought: Your reasoning - analyze the task and decide the next step.
Action: The tool name, MUST be one of [{tool_names}].
Action Input: The input for the selected tool.
Observation: The tool result.

(The Thought/Action/Action Input/Observation cycle can repeat.)

When you have gathered enough information:
Thought: I have gathered enough information.
Final Answer: The complete, detailed final answer.

---
RULES:
- All output MUST be in English.
- Prefer view_file to inspect code before using edit_file.
- For complex analysis/search, prefer delegate_to_sub_agent.
- Never guess file content - inspect first.
- If a tool returns "[SAFETY GUARD] ...", that operation was blocked.

Begin!

Question: {input}
Thought:{agent_scratchpad}
""")

        agent = create_react_agent(llm=self.llm, tools=self.tools, prompt=prompt)
        self.executor = AgentExecutor(
            agent=agent,
            tools=self.tools,
            verbose=True,            # 打开详细日志，记录 Thought/Action/Observation
            max_iterations=50,
            handle_parsing_errors=True,
            return_intermediate_steps=True,  # 返回中间步骤用于落盘
        )

    # ============================================================
    # 工具管理
    # ============================================================

    def add_tool(self, tool: Tool):
        """添加自定义工具"""
        self.tools.append(tool)
        self._build_executor()

    # ============================================================
    # 执行
    # ============================================================

    def run(self, input_text: str) -> Dict[str, Any]:
        """执行主任务"""
        if not self.executor:
            return {
                "output": "Agent 未正确初始化，可能没有工具或工作目录。",
                "success": False,
                "intermediate_steps": [],
            }

        logger.info(f"ClaudeCode 开始执行任务: {input_text[:120]}...")

        try:
            result = self.executor.invoke({'input': input_text})

            output = str(result.get('output', ''))

            # 把中间步骤（Thought/Action/Observation）序列化出来，方便 trace 文件落盘
            raw_steps = result.get('intermediate_steps', []) or []
            intermediate_steps = []
            for i, step in enumerate(raw_steps):
                try:
                    tool_name = ""
                    tool_input = ""
                    observation = ""
                    # LangChain 返回的 step 通常是 (AgentAction, observation) 元组
                    if isinstance(step, (tuple, list)) and len(step) >= 2:
                        action, observation = step[0], step[1]
                        tool_name = getattr(action, 'tool', '') or ''
                        tool_input = getattr(action, 'tool_input', '') or ''
                        log = getattr(action, 'log', '') or ''
                    else:
                        log = str(step)
                        observation = ""
                    intermediate_steps.append({
                        "step": i + 1,
                        "tool": str(tool_name),
                        "tool_input": str(tool_input)[:2000],
                        "thought": str(log)[:2000],
                        "observation": str(observation)[:2000],
                    })
                except Exception as _e:
                    intermediate_steps.append({
                        "step": i + 1, "error": f"序列化失败: {_e}", "raw": repr(step)[:500]
                    })

            logger.info("ClaudeCode 任务完成")

            return {
                "output": output,
                "success": True,
                "intermediate_steps": intermediate_steps,
                "safety_summary": self.safety_guard.summary(),
                "delegation_summary": (
                    self.delegation_manager.summary()
                    if self.delegation_manager else None
                ),
            }

        except Exception as e:
            logger.error(f"ClaudeCode 执行失败: {e}")
            return {
                "output": f"执行过程中出现错误: {e}",
                "success": False,
                "intermediate_steps": [],
                "error": str(e),
            }
