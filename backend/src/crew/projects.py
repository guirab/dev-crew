"""Projects created by dev-crew from scratch (D58) and existing repositories added from the UI.

They live in ``~/.dev-crew/repos.toml`` (managed here, never hand-edited) and are merged with the
``[[repos]]`` of ``crew.toml`` when the stack starts; a name in ``crew.toml`` wins. A new project starts
with empty commands: the Planner decides the stack and its commands (``Plan.project_setup``), saved here
once the plan is approved. An added repository is not new: it carries the commands the user typed.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import structlog
from pydantic import ValidationError

from .config import CrewConfig, RepoCfg, crew_home
from .contracts import AddRepo, ProjectSetup

log = structlog.get_logger(__name__)

REGISTRY_FILENAME = "repos.toml"
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
RESERVED_NAMES = frozenset({"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10))})

GITIGNORE = """\
# dependências e builds
node_modules/
dist/
build/
.venv/
venv/
__pycache__/
*.pyc
.pytest_cache/
.ruff_cache/
.mypy_cache/
coverage/

# segredos e locais
.env
.env.*
!.env.example
.DS_Store
Thumbs.db
"""


class ProjectError(RuntimeError):
    """Invalid request for a new project. The message is meant for the end user (pt-BR)."""


def registry_path() -> Path:
    return crew_home() / REGISTRY_FILENAME


def validate_name(name: str) -> str:
    name = name.strip()
    if not NAME_RE.fullmatch(name) or name.lower() in RESERVED_NAMES or name.endswith("."):
        raise ProjectError(
            f"nome de projeto inválido: {name!r} (use letras, números, ponto, hífen ou _; até 64)"
        )
    return name


def project_path(cfg: CrewConfig, name: str, parent_dir: str) -> Path:
    parent = Path(parent_dir).expanduser() if parent_dir.strip() else cfg.workspace.projects_dir
    if not parent.is_absolute():
        raise ProjectError(f"a pasta onde criar o projeto precisa ser um caminho absoluto: {parent}")
    if not parent.is_dir():
        raise ProjectError(f"a pasta {parent} não existe")
    return parent / name


def initial_files(name: str, title: str, description: str) -> dict[str, str]:
    body = description.strip() or title.strip()
    readme = f"# {name}\n\n{body}\n\nProjeto criado pelo dev-crew.\n"
    return {"README.md": readme, ".gitignore": GITIGNORE}


def new_repo(name: str, path: Path) -> RepoCfg:
    return RepoCfg(name=name, path=path, base_branch="main", test_cmd="", new_project=True)


def added_repo(cmd: AddRepo, path: Path) -> RepoCfg:
    """An existing repository the user registered, with the commands they typed."""
    deps = [d.strip() for d in cmd.deps_dirs if d.strip()]
    try:
        return RepoCfg(
            name=cmd.name.strip(),
            path=path,
            base_branch=cmd.base_branch.strip(),
            test_cmd=cmd.test_cmd.strip(),
            lint_cmd=(cmd.lint_cmd or "").strip() or None,
            setup_cmd=(cmd.setup_cmd or "").strip() or None,
            sandbox_image=(cmd.sandbox_image or "").strip() or None,
            deps_dirs=deps,
            new_project=False,
        )
    except ValidationError as e:
        msg = e.errors()[0]["msg"].removeprefix("Value error, ")
        raise ProjectError(msg) from e


# ------------------------------------------------------------------ registry file


def load_registered(path: Path | None = None) -> list[RepoCfg]:
    """Projects in the registry. Missing or broken file: none (logged), never an error at startup."""
    path = path or registry_path()
    if not path.is_file():
        return []
    try:
        data = tomllib.loads(path.read_text("utf-8"))
        return [RepoCfg.model_validate(r) for r in data.get("repos", [])]
    except (OSError, ValueError) as e:  # TOMLDecodeError and ValidationError are ValueErrors
        log.warning("project_registry_unreadable", path=str(path), error=str(e))
        return []


def _toml_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    return json.dumps(str(value), ensure_ascii=False)  # a JSON string is a valid TOML basic string


def dump_registry(repos: list[RepoCfg]) -> str:
    lines = ["# Projetos criados pelo dev-crew (D58). Gerido pelo dev-crew: não edite à mão.", ""]
    for repo in repos:
        lines.append("[[repos]]")
        data = repo.model_dump(mode="json")
        data["path"] = repo.path.as_posix()
        for key, value in data.items():
            if value is None:
                continue
            lines.append(f"{key} = {_toml_value(value)}")
        lines.append("")
    return "\n".join(lines)


def save_registered(repos: list[RepoCfg], path: Path | None = None) -> None:
    path = path or registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(dump_registry(repos), encoding="utf-8", newline="\n")
    tmp.replace(path)


def register(repo: RepoCfg, path: Path | None = None) -> None:
    repos = [r for r in load_registered(path) if r.name != repo.name]
    save_registered([*repos, repo], path)


def merge_registered(cfg: CrewConfig, path: Path | None = None) -> list[RepoCfg]:
    """Add the registered projects to ``cfg.repos`` (in place). ``crew.toml`` wins on a name clash."""
    known = {r.name for r in cfg.repos}
    added = [r for r in load_registered(path) if r.name not in known]
    cfg.repos.extend(added)
    return added


def with_setup(repo: RepoCfg, setup: ProjectSetup) -> RepoCfg:
    """The project after its first plan: commands decided by the Planner, no longer new."""
    data = repo.model_dump()
    data.update(
        test_cmd=setup.test_cmd,
        lint_cmd=setup.lint_cmd,
        setup_cmd=setup.setup_cmd,
        sandbox_image=setup.sandbox_image,
        deps_dirs=list(setup.deps_dirs),
        new_project=False,
    )
    return RepoCfg.model_validate(data)  # validators: empty command -> None, relative deps_dirs
