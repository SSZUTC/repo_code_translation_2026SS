"""LLM 配置 - 统一管理 Provider 和 API 配置"""
from dataclasses import dataclass, field
from typing import Optional, Dict


# LLM 提供商类型
LLMProvider = str  # 'openai' | 'ark' | 'azure' | 'anthropic' | 'ollama'


# 提供商默认 Base URL
PROVIDER_BASE_URLS: Dict[str, str] = {
    'openai': 'https://openrouter.ai/api/v1',
    'ark': 'https://openrouter.ai/api/v1',
    'azure': '',
}


@dataclass
class LLMConfig:
    provider: str = 'openai'
    api_key: str = ''
    model: str = 'openai/gpt-4o'
    temperature: float = 0.1
    max_output_tokens: int = 16384
    max_total_tokens: int = 262144
    timeout: int = 120
    base_url: Optional[str] = None
    extra: Dict = field(default_factory=dict)


# 默认配置（与 sweagent 保持一致，使用 OpenRouter）
DEFAULT_LLM_CONFIG = LLMConfig(
    provider='openai',
    api_key='',
    model='openai/gpt-4o',
    temperature=0.1,
    max_output_tokens=16384,
    max_total_tokens=262144,
)
