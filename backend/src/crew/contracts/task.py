"""Task input: spec and repository context."""

from .common import Contract


class TaskSpec(Contract):
    title: str
    description: str
    repo: str
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
    sandbox: bool = False  # True: commands run in the task's Docker container (tool `run`, not Bash)


class RepoInfo(Contract):
    """Repository as exposed to the UI (GET /api/repos)."""

    name: str
    base_branch: str
