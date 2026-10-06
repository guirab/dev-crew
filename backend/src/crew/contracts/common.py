"""Shared literal types and the base model used by every contract."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

AgentName = Literal["interviewer", "planner", "developer", "tester", "reviewer"]
AGENTS: tuple[AgentName, ...] = ("interviewer", "planner", "developer", "tester", "reviewer")

StageKey = Literal["manual", "interviewer", "planner", "approval", "developer", "tester", "reviewer", "done"]
STAGES: tuple[StageKey, ...] = (
    "manual",
    "interviewer",
    "planner",
    "approval",
    "developer",
    "tester",
    "reviewer",
    "done",
)

StageStatus = Literal["idle", "pick", "active", "waiting", "done", "error", "skipped"]

EdgeKey = Literal["ma-iv", "iv-pl", "pl-ap", "ap-dv", "dv-ts", "ts-rv", "rv-dn", "ts-dv", "rv-dv"]
EDGES: tuple[EdgeKey, ...] = (
    "ma-iv",
    "iv-pl",
    "pl-ap",
    "ap-dv",
    "dv-ts",
    "ts-rv",
    "rv-dn",
    "ts-dv",
    "rv-dv",
)

EdgeStatus = Literal["on", "active"]

TaskPhase = Literal[
    "interviewing",
    "planning",
    "awaiting_approval",
    "developing",
    "testing",
    "reviewing",
    "escalated",
    "done",
    "cancelled",
    "failed",
]
TERMINAL_PHASES: frozenset[TaskPhase] = frozenset({"done", "cancelled", "failed"})

FileChange = Literal["A", "M", "D"]
EventSource = Literal["interviewer", "planner", "developer", "tester", "reviewer", "orchestrator", "gateway"]


class Contract(BaseModel):
    """Base for all wire contracts: strict and immutable."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        # in serialization-mode JSON Schema, fields with defaults are always present → required
        json_schema_serialization_defaults_required=True,
    )
