"""Cost estimate of a plan and the account's subscription usage (D56)."""

from pydantic import AwareDatetime

from .common import Contract


class AccountUsage(Contract):
    """Subscription usage as last cached by the Claude Code CLI (percentages 0-100)."""

    plan: str | None = None  # "pro", "max"... from `claude auth status`
    session_pct: float | None = None
    session_resets_at: AwareDatetime | None = None
    weekly_pct: float | None = None
    weekly_resets_at: AwareDatetime | None = None
    fetched_at: AwareDatetime | None = None


class EpicEstimate(Contract):
    epic_id: str
    tokens: int
    usd: float


class Estimate(Contract):
    """What running the plan is expected to cost. Approximate by nature: ``basis`` says what it rests on.

    ``usd`` is the API-price equivalent (nothing is billed on a subscription). The percentages are of the
    subscription windows and need calibration from earlier tasks; ``None`` when there is none yet.
    """

    tokens: int
    usd: float
    session_pct: float | None = None
    weekly_pct: float | None = None
    sessions_needed: int | None = None  # 5-hour windows the run is expected to span
    usage_now: AccountUsage | None = None
    calibrated: bool = False
    basis: str
    epics: list[EpicEstimate] = []
