"""LLM 配置模块"""
from typing import Literal, Optional
from dataclasses import dataclass


# LLM 提供商类型
LLMProvider = Literal['openai', 'ark', 'azure', 'anthropic', 'ollama']


@dataclass
class LLMConfig:
    """LLM 配置类"""
    provider: LLMProvider
    api_key: str
    model: str
    temperature: float = 0.1
    max_output_tokens: int = 32768  # 单次输出最大 token 数
    max_total_tokens: int = 262144  # 能处理的总 token 大小（上下文窗口）
    base_url: Optional[str] = None
    timeout: int = 120


# 提供商默认 Base URL
PROVIDER_BASE_URLS: dict[LLMProvider, str] = {
    'openai': 'https://openrouter.ai/api/v1',
    'ark': 'https://openrouter.ai/api/v1',
    'azure': ''  # Azure 需要自定义 URL
}


# 默认配置
DEFAULT_LLM_CONFIG = LLMConfig(
    provider='openai',
    api_key='',
    model='openai/gpt-4o',
    temperature=0.1,
    max_output_tokens=16384,
    max_total_tokens=262144
)
