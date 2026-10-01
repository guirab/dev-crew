"""Runtime settings of one agent worker (interface agreed with Stream A)."""

from __future__ import annotations

import os
from collections.abc import Mapping

from pydantic import BaseModel

from ..contracts import AgentName

DEFAULT_MODELS: dict[AgentName, str] = {
    "interviewer": "claude-sonnet-5-5",
    "planner": "claude-opus-5-5",
    "developer": "claude-sonnet-5-5",
    "tester": "claude-sonnet-5-5",
    "reviewer": "claude-opus-5-5",
}

DEFAULT_NATS_URL = "nats://127.0.0.1:4222"


class AgentRuntimeSettings(BaseModel):
    model: str
    fake: bool = False
    fake_speed: float = 1.0
    """Playback speed of the scripted runner, like the mockup: 2.0 is twice as fast, 1000 is instant."""
    fake_escalate: bool = False
    max_turns: int | None = None


def _truthy(value: str | None) -> bool:
    return value is not None and value.strip().lower() in {"1", "true", "yes", "on"}


def settings_from_env(agent: AgentName, env: Mapping[str, str] | None = None) -> AgentRuntimeSettings:
    """Reads CREW_MODEL_<AGENT>, CREW_FAKE_AGENTS, CREW_FAKE_SPEED, CREW_FAKE_ESCALATE and CREW_MAX_TURNS."""
    env = os.environ if env is None else env
    speed = env.get("CREW_FAKE_SPEED")
    turns = env.get("CREW_MAX_TURNS")
    return AgentRuntimeSettings(
        model=env.get(f"CREW_MODEL_{agent.upper()}") or DEFAULT_MODELS[agent],
        fake=_truthy(env.get("CREW_FAKE_AGENTS")),
        fake_speed=float(speed) if speed else 1.0,
        fake_escalate=_truthy(env.get("CREW_FAKE_ESCALATE")),
        max_turns=int(turns) if turns else None,
    )


def nats_url_from_env(env: Mapping[str, str] | None = None) -> str:
    env = os.environ if env is None else env
    return env.get("CREW_NATS_URL") or DEFAULT_NATS_URL
