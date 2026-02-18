from __future__ import annotations

from .base import LLMClient, LLMConfig
from .errors import LLMError
from .openai_client import OpenAILLM


def build_llm(*, provider: str, model: str) -> LLMClient:
    """Factory for provider clients.

    Providers:
    - openai

    Extend by adding new provider clients and mapping here.
    """

    p = provider.lower().strip()
    if p == "openai":
        return OpenAILLM(
            LLMConfig(provider="openai", model=model, api_key_env="OPENAI_API_KEY")
        )

    raise LLMError(f"Unknown LLM provider: {provider}")
