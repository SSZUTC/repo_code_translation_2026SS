from langchain.callbacks.base import BaseCallbackHandler
from typing import Any, Dict, Literal, Optional, Callable, List
import logging

logger = logging.getLogger(__name__)

# LLM 提供商类型
LLMProvider = Literal['openai', 'ark']


class LLMResponseCallback(BaseCallbackHandler):
    """LLM 响应回调处理器

    用于统计单次 agent 执行的总 token 消耗
    针对不同的 LLMProvider（openai 和 ark）进行分类处理
    """

    def __init__(self, provider: LLMProvider = 'openai'):
        """初始化回调处理器

        Args:
            provider: LLM 提供商类型，支持 'openai' 和 'ark'
        """
        super().__init__()
        self.provider = provider

        # Token 统计（累加所有调用）
        self.total_tokens = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.call_count = 0  # LLM 调用次数

        # 最后一次调用的 token 统计
        self.last_call_tokens = 0
        self.last_prompt_tokens = 0
        self.last_completion_tokens = 0

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        """当 LLM 生成完成时触发，累计 token 使用量

        Args:
            response: LLMResult 对象
            **kwargs: 其他参数（未使用）
        """
        self.call_count += 1
        self._extract_token_usage(response)

    def _extract_token_usage(self, response: Any) -> None:
        """提取 token 使用量

        兼容 OpenAI 和 ARK 的响应格式：
        - 优先从 llm_output.token_usage 获取
        - 如果没有，则从 llm_output.usage 获取

        Args:
            response: LLMResult 对象
        """
        # response 是 LLMResult 对象，使用属性访问
        llm_output = getattr(response, 'llm_output', None)
        if not llm_output:
            return

        # 尝试从 token_usage 获取（OpenAI 和 LangChain 标准化后的格式）
        token_usage = llm_output.get('token_usage', None)
        if not token_usage:
            # 如果没有 token_usage，尝试从 usage 获取（ARK 原始格式）
            token_usage = llm_output.get('usage', {})

        if token_usage:
            prompt = token_usage.get('prompt_tokens', 0)
            completion = token_usage.get('completion_tokens', 0)
            total = token_usage.get('total_tokens', 0)

            # 累加总 tokens
            self.prompt_tokens += prompt
            self.completion_tokens += completion
            self.total_tokens += total

            # 记录最后一次调用的 tokens
            self.last_prompt_tokens = prompt
            self.last_completion_tokens = completion
            self.last_call_tokens = total

    def get_stats(self) -> Dict[str, Any]:
        """获取 token 使用统计

        Returns:
            包含 token 使用统计的字典，包括累加总量和最后一次调用的统计
        """
        return {
            'total_tokens': self.total_tokens,
            'prompt_tokens': self.prompt_tokens,
            'completion_tokens': self.completion_tokens,
            'call_count': self.call_count,
            'provider': self.provider,
            # 最后一次调用的统计
            'last_call_tokens': self.last_call_tokens,
            'last_prompt_tokens': self.last_prompt_tokens,
            'last_completion_tokens': self.last_completion_tokens
        }

    def reset(self) -> None:
        """重置统计数据"""
        self.total_tokens = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.call_count = 0
        self.last_call_tokens = 0
        self.last_prompt_tokens = 0
        self.last_completion_tokens = 0


class ForceStopCallback(BaseCallbackHandler):
    """强制停止回调处理器

    在每次 LLM 调用前检查是否需要强制停止，如果需要则修改 prompt
    """

    def __init__(self, should_stop_func: Callable[[], bool], threshold: int):
        """初始化强制停止回调处理器

        Args:
            should_stop_func: 判断是否需要强制停止的函数
            threshold: 强制停止的 token 阈值
        """
        super().__init__()
        self.should_stop_func = should_stop_func
        self.threshold = threshold
        self.force_stop_triggered = False

    def on_llm_start(
        self, serialized: Dict[str, Any], prompts: List[str], **kwargs: Any
    ) -> None:
        """在 LLM 开始前检查是否需要强制停止

        Args:
            serialized: LLM 序列化信息
            prompts: prompt 列表
            **kwargs: 其他参数
        """
        # 检查是否需要强制停止
        if self.should_stop_func():
            if not self.force_stop_triggered:
                self.force_stop_triggered = True
                logger.warning(f"检测到上一轮 LLM 调用超过阈值 {self.threshold}，将在本轮强制要求提供 Final Answer")

            # 修改 prompts，要求必须提供 Final Answer
            for i in range(len(prompts)):
                original_prompt = prompts[i]
                prompts[i] = f"""CRITICAL: Your previous turn exceeded the token threshold ({self.threshold} tokens).
You MUST provide a Final Answer in this turn. Do not use any more tools.
Summarize what you have found so far and provide a Final Answer immediately.

{original_prompt}"""
                logger.debug(f"已修改 prompt 以强制停止")

    def reset(self) -> None:
        """重置强制停止标志"""
        self.force_stop_triggered = False