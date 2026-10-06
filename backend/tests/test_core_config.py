from __future__ import annotations

from pathlib import Path

import pytest

from crew.config import (
    ConfigError,
    CrewConfig,
    Secrets,
    candidate_config_paths,
    crew_home,
    find_config_path,
    load_config,
    parse_config,
)
from crew.logging import configure_logging

REPO_ROOT = Path(__file__).resolve().parents[2]

MINIMAL = """
[[repos]]
name = "r"
path = "~/some/repo"
test_cmd = "pytest -q"
lint_cmd = ""
"""


def test_example_toml_is_valid() -> None:
    cfg = load_config(REPO_ROOT / "crew.toml.example")
    assert cfg.gateway.host == "127.0.0.1"
    assert cfg.limits.max_test_attempts == 3
    assert cfg.repos[0].lint_cmd is None  # "" -> None


def test_defaults_and_repo_context(tmp_path: Path) -> None:
    p = tmp_path / "crew.toml"
    p.write_text(MINIMAL, "utf-8")
    cfg = load_config(p)
    assert cfg.nats.url.startswith("nats://")
    assert cfg.workspace.mode == "worktree"
    assert "~" not in str(cfg.repos[0].path)
    ctx = cfg.repo_context("r")
    assert ctx.test_cmd == "pytest -q" and ctx.lint_cmd is None and ctx.commit_language == "pt-BR"
    assert [r.name for r in cfg.repo_infos()] == ["r"]
    assert cfg.model_for("planner") == "claude-opus-5-5"


def test_unknown_repo_lists_known() -> None:
    cfg = parse_config({"repos": [{"name": "a", "path": "/x", "test_cmd": "t"}]})
    with pytest.raises(ConfigError, match="conhecidos: a"):
        cfg.repo("b")
    assert cfg.has_repo("a") and not cfg.has_repo("b")


def test_gateway_must_be_loopback() -> None:
    with pytest.raises(ConfigError, match="loopback"):
        parse_config({"gateway": {"host": "0.0.0.0"}})


def test_duplicate_repos_and_extra_keys_rejected() -> None:
    repo = {"name": "a", "path": "/x", "test_cmd": "t"}
    with pytest.raises(ConfigError, match="duplicados"):
        parse_config({"repos": [repo, repo]})
    with pytest.raises(ConfigError):
        parse_config({"limitz": {}})


def test_lookup_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("CREW_HOME", str(home))
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CREW_CONFIG", raising=False)
    assert find_config_path() is None
    with pytest.raises(ConfigError, match="não encontrado"):
        load_config()
    (home / "crew.toml").write_text(MINIMAL, "utf-8")
    assert find_config_path() == home / "crew.toml"
    (tmp_path / "crew.toml").write_text(MINIMAL, "utf-8")
    assert find_config_path() == tmp_path / "crew.toml"
    explicit = tmp_path / "other.toml"
    explicit.write_text(MINIMAL, "utf-8")
    monkeypatch.setenv("CREW_CONFIG", str(explicit))
    assert candidate_config_paths()[0] == explicit
    assert find_config_path() == explicit
    assert crew_home() == home


def test_invalid_toml(tmp_path: Path) -> None:
    p = tmp_path / "crew.toml"
    p.write_text("[nats\n", "utf-8")
    with pytest.raises(ConfigError, match="TOML inválido"):
        load_config(p)
    with pytest.raises(ConfigError, match="não existe"):
        load_config(tmp_path / "nope.toml")


def test_secrets_from_env_never_leak_in_repr(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
    s = Secrets()
    assert s.anthropic_api_key is not None and s.anthropic_api_key.get_secret_value() == "sk-secret"
    assert "sk-secret" not in repr(s)


def test_secrets_read_dotenv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=from-dotenv\nOTHER=1\n", "utf-8")
    assert Secrets().anthropic_api_key is not None


def test_configure_logging_is_idempotent(tmp_path: Path) -> None:
    f = tmp_path / "logs" / "crew.log"
    configure_logging("INFO", log_file=f)
    configure_logging("INFO", log_file=f)
    import structlog

    structlog.get_logger("t").bind(task_id="T-1").info("hello", job_id="j")
    text = f.read_text("utf-8")
    assert '"task_id": "T-1"' in text and '"event": "hello"' in text


def test_crew_config_is_default_constructible() -> None:
    assert CrewConfig().repos == []
