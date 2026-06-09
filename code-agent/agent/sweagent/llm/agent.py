"""ReAct Agent 实现

基于 LangChain 的 ReAct Agent，支持工具调用和对话历史管理
"""
from typing import List, Optional, Dict, Any
import time
from langchain.agents import AgentExecutor, create_react_agent
from langchain.prompts import PromptTemplate
from langchain_openai import ChatOpenAI
from langchain.memory import ConversationBufferMemory
from langchain.tools import Tool
from langchain_core.messages import BaseMessage
from langchain_core.runnables import RunnableConfig

from llm.callbacks import LLMResponseCallback, ForceStopCallback

from .config import LLMConfig, PROVIDER_BASE_URLS, DEFAULT_LLM_CONFIG
from utils.logger import logger


class RetryableChatOpenAI(ChatOpenAI):
    """带重试机制的 ChatOpenAI 包装类

    重试策略：
    - 最多重试 3 次
    - RateLimitError: 等待 60 秒后重试
    - 其他错误: 等待 5 秒后重试
    """

    def invoke(self, input, config: Optional[RunnableConfig] = None, **kwargs):
        """重写 invoke 方法，添加重试逻辑"""
        max_retries = 3

        for attempt in range(max_retries):
            try:
                return super().invoke(input, config, **kwargs)
            except Exception as e:
                # 转为小写进行错误类型判断
                error_str_lower = str(e).lower()
                is_last_attempt = (attempt == max_retries - 1)

                # 检查是否是 RateLimitError（不区分大小写）
                is_rate_limit = (
                    ('rate' in error_str_lower and 'limit' in error_str_lower) or
                    'ratelimit' in error_str_lower or
                    'rate_limit' in error_str_lower or
                    '429' in error_str_lower
                )

                if is_last_attempt:
                    logger.error(f"LLM 调用失败 (重试 {attempt + 1}/{max_retries}): {str(e)}")
                    raise

                # 根据错误类型选择等待时间
                if is_rate_limit:
                    wait_time = 60
                    logger.warning(f"检测到 RateLimitError，等待 {wait_time} 秒后重试 ({attempt + 1}/{max_retries})...")
                else:
                    wait_time = 5
                    logger.warning(f"LLM 调用失败，等待 {wait_time} 秒后重试 ({attempt + 1}/{max_retries}): {str(e)}")

                time.sleep(wait_time)

        # 理论上不会到这里，因为最后一次会 raise
        raise RuntimeError("重试逻辑异常")


class ReActAgent:
    """ReAct Agent 类

    基于 LangChain 实现的 ReAct Agent，支持：
    - 添加自定义工具
    - 对话历史管理
    - Token 使用统计
    """

    def __init__(
        self,
        config: LLMConfig,
        max_context_tokens: Optional[int] = None,
        force_stop_threshold: Optional[int] = None
    ):
        """
        初始化 ReAct Agent

        Args:
            config: LLM 配置
            max_context_tokens: 最大上下文 token 数（对话历史），不设置则使用 config.max_total_tokens
            force_stop_threshold: 强制停止阈值，当总 tokens 超过此值时，要求 agent 必须结束（默认为 max_total_tokens * 0.9）
        """
        self.config = {**vars(DEFAULT_LLM_CONFIG), **vars(config)}
        self.tools: List[Tool] = []
        self.agent_executor: Optional[AgentExecutor] = None
        # max_context_tokens 用于对话历史管理，默认使用 config 中的 max_total_tokens
        self.max_context_tokens = max_context_tokens or self.config.get('max_total_tokens', 262144)
        # 强制停止阈值，默认为 max_total_tokens 的 0.9 倍
        self.force_stop_threshold = force_stop_threshold or int(self.max_context_tokens * 0.9)

        # 创建 LLM 模型
        self.llm = self._create_llm()

        self.memory = ConversationBufferMemory(
            return_messages=True,
            memory_key='chat_history',
            input_key='input',
            output_key='output'
        )

        logger.info(f"ReAct Agent 初始化完成 - Provider: {config.provider}, Model: {config.model}")

    def _create_llm(self) -> ChatOpenAI:
        """创建 LLM 模型实例（带重试机制）"""
        config = self.config
        base_url = config.get('base_url') or PROVIDER_BASE_URLS.get(
            config['provider'],
            PROVIDER_BASE_URLS['openai']
        )

        # 仅为 openai 和 ark 创建回调处理器
        provider = config['provider']
        callbacks = []
        self.callback = None
        self.force_stop_callback = None

        if provider in ['openai', 'ark']:
            self.callback = LLMResponseCallback(provider=provider)
            # 创建强制停止回调处理器
            self.force_stop_callback = ForceStopCallback(
                should_stop_func=self.should_force_stop,
                threshold=self.force_stop_threshold
            )
            callbacks = [self.callback, self.force_stop_callback]

        # 使用带重试机制的 ChatOpenAI
        llm = RetryableChatOpenAI(
            api_key=config['api_key'],
            base_url=base_url,
            model=config['model'],
            temperature=config.get('temperature', 0.1),
            max_tokens=config.get('max_output_tokens', 32768),  # 控制单次输出的最大 token 数
            timeout=config.get('timeout', 120),
            disable_streaming=True,  # 禁用流式输出，确保 token usage 可用
            callbacks=callbacks if callbacks else None  # 只在有 callback 时传入
        )

        return llm

    def add_tool(self, tool: Tool) -> None:
        """
        添加单个工具

        Args:
            tool: LangChain Tool 实例
        """
        self.tools.append(tool)
        self._rebuild_agent()
        logger.info(f"添加工具: {tool.name}")

    def add_tools(self, tools: List[Tool]) -> None:
        """
        批量添加工具

        Args:
            tools: Tool 列表
        """
        self.tools.extend(tools)
        self._rebuild_agent()
        logger.info(f"批量添加 {len(tools)} 个工具")

    def _rebuild_agent(self) -> None:
        """重建 Agent"""
        if not self.tools:
            self.agent_executor = None
            return

        # 创建 ReAct Prompt 模板
        prompt = PromptTemplate.from_template("""
You are a powerful AI assistant designed to answer user questions by using a set of available tools.

Your goal is to provide a final, accurate answer to the user's question.

TOOLS: You have access to the following tools. Only use these tools. {tools}

CONVERSATION HISTORY:
{chat_history}

INSTRUCTIONS: You must follow this format strictly. Do not add any explanations or conversational text outside of this structure.

Thought: Your reasoning process. Analyze the user's question and the conversation history, break it down into steps, and decide which tool is needed.
Action: The name of the tool to use, which must be one of [{tool_names}].
Action Input: The input for the selected tool.
Observation: The result returned by the tool.

(The Thought/Action/Action Input/Observation cycle can be repeated multiple times if necessary.)

When you have gathered enough information and are ready to provide the final answer, use this format:

Thought: I have sufficient information and can now answer the user's question. Final Answer: The complete and final answer to the original question.

IMPORTANT RULES:

Your entire output must be in English.
If the tools do not provide the necessary information, or if you cannot find an answer, state that clearly in your "Final Answer".
Base your "Final Answer" only on the information gathered from the "Observation" steps and the conversation history.

Begin!

Question: {input}
Thought:{agent_scratchpad}
""")

        # 创建 ReAct Agent
        agent = create_react_agent(
            llm=self.llm,
            tools=self.tools,
            prompt=prompt
        )

        # 创建 Agent Executor
        # 注意：callbacks 通过 LLM 传递，不需要在这里重复设置
        self.agent_executor = AgentExecutor(
            agent=agent,
            tools=self.tools,
            verbose=False,
            max_iterations=1000,
            return_intermediate_steps=False,
            memory=self.memory,
            handle_parsing_errors=True
        )

        logger.debug("Agent 重建完成")

    def run(self, input_text: str) -> Dict[str, Any]:
        """
        运行 Agent

        Args:
            input_text: 用户输入

        Returns:
            包含输出和中间步骤的字典
        """
        if not self.agent_executor:
            raise ValueError("没有可用的智能体。请先使用 add_tool() 或 add_tools() 添加工具")

        try:
            logger.info(f"执行任务: {input_text[:100]}...")

            result = self.agent_executor.invoke({'input': input_text})

            logger.info("任务执行完成")

            return {
                'output': result['output'],
                'intermediate_steps': result.get('intermediate_steps', [])
            }

        except Exception as e:
            error_msg = f"ReAct Agent 执行失败: {str(e)}"
            logger.error(error_msg)

            # 返回友好的错误响应
            return {
                'output': f'抱歉，执行过程中遇到了错误: {str(e)}',
                'intermediate_steps': []
            }

    def get_tools(self) -> List[Dict[str, str]]:
        """
        获取所有工具信息

        Returns:
            工具信息列表
        """
        return [
            {'name': tool.name, 'description': tool.description}
            for tool in self.tools
        ]

    def remove_tool(self, name: str) -> bool:
        """
        移除指定工具

        Args:
            name: 工具名称

        Returns:
            是否成功移除
        """
        original_len = len(self.tools)
        self.tools = [tool for tool in self.tools if tool.name != name]

        if len(self.tools) < original_len:
            self._rebuild_agent()
            logger.info(f"移除工具: {name}")
            return True

        return False

    def clear_tools(self) -> None:
        """清空所有工具"""
        self.tools = []
        self.agent_executor = None
        logger.info("清空所有工具")

    def clear_context(self) -> None:
        """清空对话历史"""
        self.memory.clear()
        logger.info("清空对话历史")

    async def get_context(self) -> Dict[str, Any]:
        """
        获取当前上下文信息

        Returns:
            包含对话历史的字典（不包含 token 统计，避免 ARK 模型的 token 计算问题）
        """
        messages: List[BaseMessage] = await self.memory.chat_memory.aget_messages()

        conversation_history = [
            {
                'role': 'user' if msg.type == 'human' else 'assistant',
                'content': str(msg.content)
            }
            for msg in messages
        ]

        return {
            'conversation_history': conversation_history,
            'message_count': len(messages)
        }

    async def get_token_usage_stats(self) -> Dict[str, Any]:
        """
        获取对话统计信息

        Returns:
            包含对话统计的字典
        """
        context = await self.get_context()

        stats = {
            'message_count': context['message_count'],
            'max_total_tokens': self.max_context_tokens,
            'force_stop_threshold': self.force_stop_threshold
        }

        # 如果有 callback，添加 token 使用统计
        if self.callback:
            token_stats = self.callback.get_stats()
            stats.update(token_stats)
            # 添加是否接近阈值的标志
            stats['near_threshold'] = self.callback.total_tokens >= self.force_stop_threshold * 0.9
            stats['exceeded_threshold'] = self.callback.total_tokens >= self.force_stop_threshold

        return stats

    def should_force_stop(self) -> bool:
        """
        检查是否应该强制停止（基于最后一轮的 token 使用）

        Returns:
            如果最后一轮 LLM 调用的 token 使用超过阈值，返回 True
        """
        if self.callback:
            return self.callback.last_call_tokens >= self.force_stop_threshold
        return False

    def get_current_token_usage(self) -> int:
        """
        获取当前已使用的 token 数

        Returns:
            已使用的总 token 数
        """
        if self.callback:
            return self.callback.total_tokens
        return 0
