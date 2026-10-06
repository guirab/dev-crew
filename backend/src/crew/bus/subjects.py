"""NATS subjects, stream and consumer names. Frozen after M0."""

from ..contracts import AgentName, EventKind

STREAM_JOBS = "CREW_JOBS"
STREAM_EVENTS = "CREW_EVENTS"

JOBS_WILDCARD = "crew.job.>"
EVENTS_WILDCARD = "crew.evt.>"

CMD = "crew.cmd"
STATE_CURRENT = "crew.state.current"

ORCHESTRATOR_DURABLE = "orchestrator"


def job_subject(agent: AgentName) -> str:
    return f"crew.job.{agent}"


def agent_durable(agent: AgentName) -> str:
    return agent


def evt_subject(task_id: str, kind: EventKind) -> str:
    return f"crew.evt.{task_id}.{kind}"


def evt_kind_wildcard(kind: EventKind) -> str:
    """All tasks, one event kind: ``crew.evt.*.<kind>``."""
    return f"crew.evt.*.{kind}"


def cancel_subject(task_id: str) -> str:
    return f"crew.ctl.{task_id}.cancel"


def parse_evt_subject(subject: str) -> tuple[str, str]:
    """``crew.evt.T-7.result`` -> (``T-7``, ``result``)."""
    parts = subject.split(".")
    if len(parts) != 4 or parts[0] != "crew" or parts[1] != "evt":
        raise ValueError(f"not an event subject: {subject}")
    return parts[2], parts[3]
