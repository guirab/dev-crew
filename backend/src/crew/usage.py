"""Subscription usage of the logged-in Claude account (D56).

Two sources, both maintained by the Claude Code CLI, neither a documented API:
- ``~/.claude.json`` → ``cachedUsageUtilization``: the last session (5 h) and weekly percentages the CLI
  fetched, with their reset times. Only those keys are read; the file also holds account data that never
  leaves this module. The CLI re-measures only when asked, so ``claude -p /usage`` is run first (no model
  call) to keep it current.
- ``claude auth status`` (JSON) → ``subscriptionType``: the plan ("pro", "max"...).

Everything is best effort: a missing or changed file yields ``None`` fields, never an error.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from .contracts import AccountUsage

log = structlog.get_logger(__name__)

PLAN_TTL_S = 600.0
REFRESH_TTL_S = 60.0  # the UI polls every 60 s: at most one ~4 s CLI call per poll
REFRESH_TIMEOUT_S = 40.0


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


def refresh_cli_cache(exe: str) -> bool:
    """Ask the CLI to measure the usage now: ``claude -p /usage`` rewrites ``cachedUsageUtilization``.

    A slash command answered locally: no model call, no quota spent, ~4 s. ``True`` when it exited 0.
    """
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0  # type: ignore[attr-defined,unused-ignore]
    try:
        proc = subprocess.run(
            [exe, "-p", "/usage", "--no-session-persistence"],
            capture_output=True,
            timeout=REFRESH_TIMEOUT_S,
            check=False,
            cwd=tempfile.gettempdir(),
            creationflags=flags,
        )
    except (OSError, subprocess.TimeoutExpired):
        log.warning("usage_refresh_unavailable")
        return False
    return proc.returncode == 0


class UsageReader:
    """Account usage, measured by the CLI on demand (cache refreshed at most every ``REFRESH_TTL_S``).

    The CLI only re-measures when something asks it to, so ``~/.claude.json`` alone drifts for days. When
    the refresh fails the stale cache is still returned, with ``fetched_at`` telling how old it is.
    """

    def __init__(
        self, *, state_path: Path | None = None, cli: str | None = None, refresh: bool = True
    ) -> None:
        self.state_path = state_path
        self.cli = cli
        self.refresh = refresh
        self._plan: str | None = None
        self._plan_at = 0.0
        self._refreshed_at: float | None = None
        self._refresh_lock = asyncio.Lock()

    def _cli_exe(self) -> str | None:
        if self.cli is not None:
            return self.cli
        from .doctor import find_claude_cli

        return find_claude_cli()

    async def measure(self, max_age_s: float = REFRESH_TTL_S) -> None:
        """Refresh the CLI cache unless it was refreshed less than ``max_age_s`` ago. One call at a time."""
        if not self.refresh:
            return
        async with self._refresh_lock:
            loop = asyncio.get_running_loop()
            if self._refreshed_at is not None and loop.time() - self._refreshed_at < max_age_s:
                return
            exe = self._cli_exe()
            if exe is None:
                return
            await asyncio.to_thread(refresh_cli_cache, exe)
            self._refreshed_at = loop.time()  # stamped on failure too: no retry storm

    async def plan(self) -> str | None:
        loop = asyncio.get_running_loop()
        if self._plan_at and loop.time() - self._plan_at < PLAN_TTL_S:
            return self._plan
        exe = self._cli_exe()
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

    async def read(self, max_age_s: float = REFRESH_TTL_S) -> AccountUsage:
        """Usage no older than ``max_age_s`` when the CLI cooperates (``0``: measure again right now)."""
        await self.measure(max_age_s)
        plan = await self.plan()
        return await asyncio.to_thread(read_cached_usage, self.state_path, plan=plan)
