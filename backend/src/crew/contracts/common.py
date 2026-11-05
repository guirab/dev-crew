"""Shared literal types and the base model used by every contract."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

AgentName = Literal["interviewer", "standards", "planner", "developer", "tester", "reviewer"]
AGENTS: tuple[AgentName, ...] = ("interviewer", "standards", "planner", "developer", "tester", "reviewer")

StageKey = Literal[
    "manual", "interviewer", "standards", "planner", "approval", "developer", "tester", "reviewer", "done"
]
STAGES: tuple[StageKey, ...] = (
    "manual",
    "interviewer",
    "standards",  # D82: runs alongside the interview; the Planner waits for both
    "planner",
    "approval",
    "developer",
    "tester",
    "reviewer",
    "done",
)

StageStatus = Literal["idle", "pick", "active", "waiting", "done", "error", "skipped"]

EdgeKey = Literal[
    "ma-iv", "iv-pl", "pl-ap", "ap-dv", "dv-ts", "ts-rv", "rv-dn", "ts-dv", "rv-dv", "ma-st", "st-pl"
]
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
    "ma-st",  # D82: start -> standards (parallel to ma-iv)
    "st-pl",  # D82: standards -> planner (parallel to iv-pl)
)

EdgeStatus = Literal["on", "active"]

TaskPhase = Literal[
    "interviewing",
    "planning",
    "awaiting_approval",
    "developing",
    "testing",
    "reviewing",
    "executing",  # split plan: epic lanes running (per-lane detail in TaskView.epics)
    "awaiting_selection",  # split plan: the chosen epics are merged, others wait for the user
    "escalated",
    "limited",  # subscription usage limit hit: waits for the user to resume after the reset (D50)
    "done",
    "cancelled",
    "failed",
]
TERMINAL_PHASES: frozenset[TaskPhase] = frozenset({"done", "cancelled", "failed"})

FileChange = Literal["A", "M", "D"]
EventSource = Literal[
    "interviewer", "standards", "planner", "developer", "tester", "reviewer", "orchestrator", "gateway"
]


class Contract(BaseModel):
    """Base for all wire contracts: strict and immutable."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        # in serialization-mode JSON Schema, fields with defaults are always present → required
        json_schema_serialization_defaults_required=True,
    )
