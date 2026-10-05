"""Configuration: ``crew.toml`` (structure) + ``.env`` (secrets) via pydantic-settings."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .contracts import AgentName, RepoContext, RepoInfo

CONFIG_ENV = "CREW_CONFIG"
HOME_ENV = "CREW_HOME"
CONFIG_FILENAME = "crew.toml"


class ConfigError(RuntimeError):
    """Invalid or missing configuration. The message is meant for the end user (pt-BR)."""


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


def crew_home() -> Path:
    """Data dir (db, logs, default worktrees). ``CREW_HOME`` overrides ``~/.dev-crew``."""
    override = os.environ.get(HOME_ENV)
    return Path(override).expanduser() if override else Path.home() / ".dev-crew"


class NatsCfg(_Section):
    url: str = "nats://127.0.0.1:4222"


class GatewayCfg(_Section):
    host: str = "127.0.0.1"
    port: int = Field(default=8787, ge=0, le=65535)

    @field_validator("host")
    @classmethod
    def _loopback_only(cls, v: str) -> str:
        # the gateway has no auth: it must never listen on a public interface
        if v not in {"127.0.0.1", "localhost"}:
            raise ValueError("gateway só pode escutar em loopback (127.0.0.1 ou localhost)")
        return v


class WorkspaceCfg(_Section):
    root: Path = Field(default_factory=lambda: crew_home() / "worktrees")
    mode: Literal["worktree", "inplace"] = "worktree"

    @field_validator("root")
    @classmethod
    def _expand(cls, v: Path) -> Path:
        return v.expanduser()


class LimitsCfg(_Section):
    max_test_attempts: int = Field(default=3, ge=1)
    max_review_rounds: int = Field(default=2, ge=1)
    budget_usd_per_task: float = Field(default=5.0, gt=0)
    job_timeout_min: float = Field(default=20.0, gt=0)


class ModelsCfg(_Section):
    interviewer: str = "claude-sonnet-5-5"
    planner: str = "claude-opus-5-5"
    developer: str = "claude-sonnet-5-5"
    tester: str = "claude-sonnet-5-5"
    reviewer: str = "claude-opus-5-5"

    def for_agent(self, agent: AgentName) -> str:
        return str(getattr(self, agent))


class CommitCfg(_Section):
    language: str = "pt-BR"
    style: str = "conventional"


class RepoCfg(_Section):
    name: str
    path: Path
    base_branch: str = "main"
    test_cmd: str
    lint_cmd: str | None = None
    test_globs: list[str] = Field(default_factory=list)
    setup_cmd: str | None = None  # run by dev-crew (never the agents) before the first agent
    sandbox_image: str | None = None  # Docker image: agent commands run in a per-task container
    deps_dirs: list[str] = Field(default_factory=list)  # kept in Docker volumes, e.g. node_modules

    @field_validator("path")
    @classmethod
    def _expand(cls, v: Path) -> Path:
        return v.expanduser()

    @field_validator("lint_cmd", "setup_cmd", "sandbox_image")
    @classmethod
    def _empty_is_none(cls, v: str | None) -> str | None:
        return v or None

    @field_validator("deps_dirs")
    @classmethod
    def _relative_dirs(cls, v: list[str]) -> list[str]:
        for d in v:
            if not d or d.startswith(("/", "\\")) or ":" in d or ".." in Path(d).parts:
                raise ValueError(f"deps_dirs precisa de caminhos relativos ao repo: {d!r}")
        return [d.replace("\\", "/").strip("/") for d in v]


class Secrets(BaseSettings):
    """Values from the environment / ``.env``. Never logged (``SecretStr``)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    anthropic_api_key: SecretStr | None = None


class CrewConfig(_Section):
    nats: NatsCfg = Field(default_factory=NatsCfg)
    gateway: GatewayCfg = Field(default_factory=GatewayCfg)
    workspace: WorkspaceCfg = Field(default_factory=WorkspaceCfg)
    limits: LimitsCfg = Field(default_factory=LimitsCfg)
    models: ModelsCfg = Field(default_factory=ModelsCfg)
    commit: CommitCfg = Field(default_factory=CommitCfg)
    repos: list[RepoCfg] = Field(default_factory=list)

    @field_validator("repos")
    @classmethod
    def _unique_names(cls, v: list[RepoCfg]) -> list[RepoCfg]:
        names = [r.name for r in v]
        dup = {n for n in names if names.count(n) > 1}
        if dup:
            raise ValueError(f"repositórios duplicados em [[repos]]: {', '.join(sorted(dup))}")
        return v

    def repo(self, name: str) -> RepoCfg:
        for r in self.repos:
            if r.name == name:
                return r
        known = ", ".join(r.name for r in self.repos) or "(nenhum)"
        raise ConfigError(f"repositório {name!r} não existe em crew.toml (conhecidos: {known})")

    def has_repo(self, name: str) -> bool:
        return any(r.name == name for r in self.repos)

    def repo_context(self, name: str) -> RepoContext:
        r = self.repo(name)
        return RepoContext(
            name=r.name,
            base_branch=r.base_branch,
            test_cmd=r.test_cmd,
            lint_cmd=r.lint_cmd,
            test_globs=list(r.test_globs),
            commit_language=self.commit.language,
            sandbox=r.sandbox_image is not None,
        )

    def repo_infos(self) -> list[RepoInfo]:
        return [RepoInfo(name=r.name, base_branch=r.base_branch) for r in self.repos]

    def model_for(self, agent: AgentName) -> str:
        return self.models.for_agent(agent)


def db_path() -> Path:
    return crew_home() / "crew.db"


def log_dir() -> Path:
    return crew_home() / "logs"


def candidate_config_paths() -> list[Path]:
    paths: list[Path] = []
    env = os.environ.get(CONFIG_ENV)
    if env:
        paths.append(Path(env).expanduser())
    paths.append(Path.cwd() / CONFIG_FILENAME)
    paths.append(crew_home() / CONFIG_FILENAME)
    return paths


def find_config_path() -> Path | None:
    for p in candidate_config_paths():
        if p.is_file():
            return p
    return None


def parse_config(data: dict[str, Any]) -> CrewConfig:
    try:
        return CrewConfig.model_validate(data)
    except ValueError as e:  # pydantic ValidationError is a ValueError
        raise ConfigError(f"crew.toml inválido:\n{e}") from e


def load_config(path: Path | None = None) -> CrewConfig:
    """Load ``crew.toml`` from ``path`` or the default lookup (``CREW_CONFIG`` > ./ > ~/.dev-crew)."""
    if path is None:
        path = find_config_path()
        if path is None:
            tried = ", ".join(str(p) for p in candidate_config_paths())
            raise ConfigError(f"crew.toml não encontrado (procurei em: {tried}). Copie crew.toml.example.")
    elif not path.is_file():
        raise ConfigError(f"arquivo de configuração não existe: {path}")
    try:
        data = tomllib.loads(path.read_text("utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: TOML inválido: {e}") from e
    return parse_config(data)


def load_secrets() -> Secrets:
    return Secrets()
