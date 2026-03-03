from __future__ import annotations

from pathlib import Path
from typing import Any

from .gemini_client import GeminiGrader


def get_llm_provider(
    provider_name: str,
    api_key: str,
    model: str,
    cache_dir: Path,
) -> Any:
    """Factory to instantiate the appropriate grader provider."""
    normalized = str(provider_name).strip().lower()

    if normalized == "gemini":
        return GeminiGrader(
            api_key=api_key,
            model=model,
            cache_dir=cache_dir,
        )
    elif normalized == "openai":
        raise NotImplementedError(
            "OpenAI provider is not yet implemented. "
            "You can add an OpenAIGrader in grader/providers/openai.py."
        )
    elif normalized == "anthropic":
        raise NotImplementedError(
            "Anthropic provider is not yet implemented. "
            "You can add an AnthropicGrader in grader/providers/anthropic.py."
        )
    else:
        raise ValueError(f"Unknown LLM provider: {provider_name}")
