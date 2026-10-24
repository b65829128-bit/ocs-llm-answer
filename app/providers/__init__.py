from __future__ import annotations

from ..config import Settings
from .base import LLMError, LLMProvider, LLMResult
from .deepseek import DeepSeekProvider, supports_vision
from .mock import MockProvider


class ConfigErrorProvider:
    """Key 没配时也能启动，但每次请求给出明确错误。"""

    name = "deepseek"

    async def complete(self, messages, model, max_tokens, temperature) -> LLMResult:
        raise LLMError("DEEPSEEK_API_KEY 未配置，请在 .env 中填写后重启服务。")


def build_provider(settings: Settings) -> LLMProvider:
    if settings.provider == "mock":
        return MockProvider()
    if settings.provider == "deepseek":
        if not settings.deepseek_api_key:
            return ConfigErrorProvider()
        return DeepSeekProvider(settings)
    raise ValueError(f"不支持的 LLM_PROVIDER: {settings.provider}（可选 deepseek / mock）")


__all__ = [
    "LLMError",
    "LLMProvider",
    "LLMResult",
    "DeepSeekProvider",
    "MockProvider",
    "build_provider",
    "supports_vision",
]
