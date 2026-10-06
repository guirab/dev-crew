"""Subscription usage of the logged-in Claude account (D56).

Two sources, both maintained by the Claude Code CLI, neither a documented API:
- ``~/.claude.json`` → ``cachedUsageUtilization``: the last session (5 h) and weekly percentages the CLI
  fetched, with their reset times. Only those keys are read; the file also holds account data that never
  leaves this module.
- ``claude auth status`` (JSON) → ``subscriptionType``: the plan ("pro", "max"...).

Everything is best effort: a missing or changed file yields ``None`` fields, never an error.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from .contracts import AccountUsage

log = structlog.get_logger(__name__)

PLAN_TTL_S = 600.0


def cli_state_path() -> Path:
    return Path.home() / ".claude.json"


def _pct(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _when(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _window(utilization: dict[str, Any], key: str) -> tuple[float | None, datetime | None]:
    entry = utilization.get(key)
    if not isinstance(entry, dict):
        return None, None
    return _pct(entry.get("utilization")), _when(entry.get("resets_at"))


def read_cached_usage(path: Path | None = None, *, plan: str | None = None) -> AccountUsage:
    """Usage as the CLI last cached it. Never raises."""
    try:
        raw = json.loads((path or cli_state_path()).read_text(encoding="utf-8"))
        cached = raw.get("cachedUsageUtilization") if isinstance(raw, dict) else None
    except (OSError, ValueError):
        return AccountUsage(plan=plan)
    if not isinstance(cached, dict):
        return AccountUsage(plan=plan)
    utilization = cached.get("utilization")
    if not isinstance(utilization, dict):
        utilization = {}
    session, session_reset = _window(utilization, "five_hour")
    weekly, weekly_reset = _window(utilization, "seven_day")
    fetched_ms = cached.get("fetchedAtMs")
    fetched = (
        datetime.fromtimestamp(fetched_ms / 1000, UTC)
        if isinstance(fetched_ms, int | float) and not isinstance(fetched_ms, bool)
        else None
    )
    return AccountUsage(
        plan=plan,
        session_pct=session,
        session_resets_at=session_reset,
        weekly_pct=weekly,
        weekly_resets_at=weekly_reset,
        fetched_at=fetched,
    )


def parse_auth_status(stdout: bytes | str) -> str | None:
    """``subscriptionType`` of ``claude auth status`` (``None`` when logged out or unreadable)."""
    try:
        info = json.loads(stdout)
    except ValueError:
        return None
    if not isinstance(info, dict) or not info.get("loggedIn"):
        return None
    plan = info.get("subscriptionType")
    return plan if isinstance(plan, str) and plan else None


class UsageReader:
    """Account usage with the plan cached for a while (``claude auth status`` takes ~1 s)."""

    def __init__(self, *, state_path: Path | None = None, cli: str | None = None) -> None:
        self.state_path = state_path
        self.cli = cli
        self._plan: str | None = None
        self._plan_at = 0.0

    async def plan(self) -> str | None:
        loop = asyncio.get_running_loop()
        if self._plan_at and loop.time() - self._plan_at < PLAN_TTL_S:
            return self._plan
        exe = self.cli
        if exe is None:
            from .doctor import find_claude_cli

            exe = find_claude_cli()
        if exe is None:
            return None
        try:
            proc = await asyncio.to_thread(
                subprocess.run, [exe, "auth", "status"], capture_output=True, timeout=30, check=False
            )
        except (OSError, subprocess.TimeoutExpired):
            log.warning("auth_status_unavailable")
            return self._plan
        self._plan = parse_auth_status(proc.stdout)
        self._plan_at = loop.time()
        return self._plan

    async def read(self) -> AccountUsage:
        plan = await self.plan()
        return await asyncio.to_thread(read_cached_usage, self.state_path, plan=plan)
