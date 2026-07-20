from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    cost_usd: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cached_tokens": self.cached_tokens,
            "cost_usd": round(self.cost_usd, 6),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> TokenUsage:
        if not data or not isinstance(data, dict):
            return TokenUsage()
        return cls(
            input_tokens=int(data.get("input_tokens", 0)),
            output_tokens=int(data.get("output_tokens", 0)),
            cached_tokens=int(data.get("cached_tokens", 0)),
            cost_usd=float(data.get("cost_usd", 0.0)),
        )

    def __add__(self, other: TokenUsage) -> TokenUsage:
        if not isinstance(other, TokenUsage):
            return self
        return TokenUsage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cached_tokens=self.cached_tokens + other.cached_tokens,
            cost_usd=round(self.cost_usd + other.cost_usd, 6),
        )


# Default model rates per 1,000,000 tokens (USD)
DEFAULT_MODEL_PRICING: dict[str, dict[str, float]] = {
    "gemini-2.5-flash": {"input": 0.075, "cached_input": 0.01875, "output": 0.30},
    "gemini-1.5-flash": {"input": 0.075, "cached_input": 0.01875, "output": 0.30},
    "gemini-2.0-flash": {"input": 0.10, "cached_input": 0.025, "output": 0.40},
    "gemini-2.5-pro": {"input": 1.25, "cached_input": 0.3125, "output": 5.00},
    "gemini-1.5-pro": {"input": 1.25, "cached_input": 0.3125, "output": 5.00},
}

FALLBACK_PRICING = {"input": 0.10, "cached_input": 0.025, "output": 0.40}


def get_model_rates(model_name: str, custom_pricing: dict[str, dict[str, float]] | None = None) -> dict[str, float]:
    model_key = (model_name or "").lower().strip()
    if custom_pricing and model_key in custom_pricing:
        return custom_pricing[model_key]
    
    for key, rates in DEFAULT_MODEL_PRICING.items():
        if key in model_key or model_key in key:
            return rates
            
    return FALLBACK_PRICING


def calculate_cost(
    model_name: str,
    input_tokens: int,
    output_tokens: int,
    cached_tokens: int = 0,
    custom_pricing: dict[str, dict[str, float]] | None = None,
) -> TokenUsage:
    rates = get_model_rates(model_name, custom_pricing)
    
    # Non-cached input tokens are billed at full input rate
    uncached_input = max(0, input_tokens - cached_tokens)
    
    input_cost = (uncached_input / 1_000_000.0) * rates.get("input", 0.0)
    cached_cost = (cached_tokens / 1_000_000.0) * rates.get("cached_input", rates.get("input", 0.0) * 0.25)
    output_cost = (output_tokens / 1_000_000.0) * rates.get("output", 0.0)
    
    total_cost = input_cost + cached_cost + output_cost
    
    return TokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_tokens=cached_tokens,
        cost_usd=round(total_cost, 6),
    )


def extract_token_usage(
    response: Any,
    model_name: str,
    custom_pricing: dict[str, dict[str, float]] | None = None,
) -> TokenUsage:
    if response is None:
        return TokenUsage()

    usage = getattr(response, "usage_metadata", None)
    if usage is None and isinstance(response, dict):
        usage = response.get("usage_metadata")

    if usage is None:
        return TokenUsage()

    if isinstance(usage, dict):
        input_tokens = usage.get("prompt_token_count") or usage.get("input_tokens") or 0
        output_tokens = usage.get("candidates_token_count") or usage.get("output_tokens") or 0
        cached_tokens = usage.get("cached_content_token_count") or usage.get("cached_tokens") or 0
    else:
        input_tokens = getattr(usage, "prompt_token_count", None) or getattr(usage, "input_tokens", 0) or 0
        output_tokens = getattr(usage, "candidates_token_count", None) or getattr(usage, "output_tokens", 0) or 0
        cached_tokens = getattr(usage, "cached_content_token_count", None) or getattr(usage, "cached_tokens", 0) or 0

    return calculate_cost(
        model_name=model_name,
        input_tokens=int(input_tokens),
        output_tokens=int(output_tokens),
        cached_tokens=int(cached_tokens),
        custom_pricing=custom_pricing,
    )

