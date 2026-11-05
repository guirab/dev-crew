from __future__ import annotations

from pathlib import Path

import pytest

from crew.agents import standards
from crew.agents.context import STANDARDS_NOTE, system_prompt_text
from crew.agents.runner import build_options
from crew.agents.settings import AgentRuntimeSettings
from crew.agents.specs import SPECS
from crew.agents.submit import make_submit_tool

from .factories import POSIX_WS, make_job, make_repo

CONVENTIONS = """# Conventions

## Service Boundaries
Only the orchestrator decides the flow.

## Testing
Every bug fix ships a regression test.
"""


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, "utf-8")
    return path


def _single(tmp_path: Path) -> Path:
    base = tmp_path / "vault" / "standards"
    _write(base / "Before You Develop.md", "# Before You Develop: app\n\nRead the conventions.")
    _write(base / "Conventions.md", CONVENTIONS)
    _write(base / "Glossary.md", "# Glossary\n\n**Lane**: one epic's pipeline.")
    _write(base / "decisions" / "ADR-0002 - Bus.md", "---\nstatus: accepted\n---\n\n# Use NATS")
    _write(base / "decisions" / "ADR-0001 - Old.md", "---\nstatus: superseded by ADR-0002\n---\n\n# Redis")
    return base


def _workspace(tmp_path: Path) -> Path:
    base = tmp_path / "vault" / "standards"
    _write(base / "Glossary.md", "# Glossary\n\n**Crew**: the agents.")
    _write(
        base / "Conventions.md", "# Conventions\n\n## Test naming\nProject wide.\n\n## Git\nSmall commits."
    )
    _write(base / "decisions" / "ADR-0001 - Mine.md", "---\nstatus: accepted\nrepos: [api, web]\n---\n# Mine")
    _write(base / "decisions" / "ADR-0002 - Other.md", "---\nstatus: accepted\nrepos:\n  - web\n---\n# Other")
    _write(base / "decisions" / "ADR-0003 - All.md", "---\nstatus: proposed\n---\n# All repos")
    _write(base / "decisions" / "ADR-0004 - Gone.md", "---\nstatus: deprecated\nrepos: [api]\n---\n# Gone")
    repo = base / "api"
    _write(repo / "Before You Develop.md", "# Before You Develop: api")
    _write(repo / "Conventions.md", CONVENTIONS.replace("# Conventions", "# Conventions: api"))
    return repo


def test_single_repo_reads_everything_in_order_without_retired_adrs(tmp_path: Path) -> None:
    text = standards.load(_single(tmp_path), "developer")
    order = [
        "### standards/Before You Develop.md",
        "### standards/Conventions.md",
        "### standards/Glossary.md",
        "### standards/decisions/ADR-0002 - Bus.md",
    ]
    assert [text.index(h) for h in order] == sorted(text.index(h) for h in order)
    assert "Use NATS" in text and "Redis" not in text and "[omitidos" not in text


def test_workspace_merges_project_level_and_filters_adrs_by_repo(tmp_path: Path) -> None:
    text = standards.load(_workspace(tmp_path), "reviewer")
    order = [
        "### standards/api/Before You Develop.md",
        "### standards/api/Conventions.md",
        "### standards/Conventions.md",
        "### standards/Glossary.md",
        "### standards/decisions/ADR-0001 - Mine.md",
        "### standards/decisions/ADR-0003 - All.md",
    ]
    assert [text.index(h) for h in order] == sorted(text.index(h) for h in order)
    assert "ADR-0002" not in text  # only for web (block list)
    assert "ADR-0004" not in text  # deprecated


def test_tester_gets_only_the_testing_sections_of_the_conventions(tmp_path: Path) -> None:
    text = standards.load(_workspace(tmp_path), "tester")
    assert "regression test" in text and "Project wide." in text
    assert "orchestrator decides" not in text and "Small commits" not in text
    assert "Glossary" not in text and "ADR" not in text and "Before You Develop" not in text


def test_interviewer_and_missing_base_get_nothing(tmp_path: Path) -> None:
    assert standards.load(_single(tmp_path), "interviewer") == ""
    assert standards.load(None, "developer") == ""
    assert standards.load(tmp_path / "nope", "developer") == ""
    (tmp_path / "empty").mkdir()
    assert standards.load(tmp_path / "empty", "planner") == ""


def test_files_that_do_not_fit_are_listed_never_cut(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    base = _single(tmp_path)
    _write(base / "Glossary.md", "x" * 500)
    monkeypatch.setattr(standards, "MAX_CHARS", 400)
    text = standards.load(base, "planner")
    assert "x" * 500 not in text and "Read the conventions." in text
    assert text.endswith("[omitidos por tamanho: standards/Glossary.md]")


def test_unreadable_file_is_skipped(tmp_path: Path) -> None:
    base = _single(tmp_path)
    (base / "Glossary.md").write_bytes(b"\xff\xfe\x00bad")
    text = standards.load(base, "developer")
    assert "Glossary" not in text and "Read the conventions." in text


def test_system_prompt_has_the_section_only_with_standards(tmp_path: Path) -> None:
    assert "## Padrões do projeto" not in system_prompt_text("developer")
    with_base = system_prompt_text("developer", "### standards/Conventions.md\n\nRule.")
    assert with_base.rstrip().endswith("Rule.") and STANDARDS_NOTE in with_base

    spec = SPECS["developer"]
    submit = make_submit_tool(spec.output, spec.submit_name, check=spec.check)
    job = make_job("developer", workspace=POSIX_WS)
    configured = AgentRuntimeSettings(model="m", standards_dirs={make_repo().name: _single(tmp_path)})
    opts = build_options(spec, job, configured, POSIX_WS, submit, resumed=False)
    assert "## Padrões do projeto" in opts.system_prompt["append"]  # type: ignore[index]
    plain = build_options(spec, job, AgentRuntimeSettings(model="m"), POSIX_WS, submit, resumed=False)
    assert "## Padrões do projeto" not in plain.system_prompt["append"]  # type: ignore[index]
