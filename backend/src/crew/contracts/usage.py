"""Token usage and subscription usage limits."""

from typing import Literal

from pydantic import AwareDatetime

from .common import Contract


class TokenUsage(Contract):
    """Tokens one model consumed in a job (from the SDK ``model_usage``). ``cost_usd`` is the API price
    equivalent: on a subscription nothing is billed, it only feeds estimates."""

    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0.0


UsageLimitKind = Literal["session", "weekly", "weekly_opus", "weekly_sonnet", "unknown"]


class UsageLimit(Contract):
    """The subscription usage limit was hit (D50): work stops until ``resets_at``."""

    kind: UsageLimitKind
    resets_at: AwareDatetime | None = None
    message: str
