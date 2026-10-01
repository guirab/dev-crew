"""Task input: work items, spec and repository context."""

from .common import Contract, TaskSource


class WorkItemSummary(Contract):
    id: int
    type: str
    title: str
    state: str


class WorkItemDetail(WorkItemSummary):
    description: str
    acceptance_criteria: list[str] = []
    iteration_path: str | None = None
    url: str


class TaskSpec(Contract):
    title: str
    description: str
    source: TaskSource
    repo: str
    work_item: WorkItemDetail | None = None
    acceptance_criteria: list[str] = []
    out_of_scope: list[str] = []
    constraints: list[str] = []
    decisions: list[str] = []


class RepoContext(Contract):
    name: str
    base_branch: str
    test_cmd: str
    lint_cmd: str | None = None
    test_globs: list[str]
    commit_language: str = "pt-BR"


class RepoInfo(Contract):
    """Repository as exposed to the UI (GET /api/repos)."""

    name: str
    base_branch: str
