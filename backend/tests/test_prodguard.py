"""Production snapshot used by the diff after the Tester (D42)."""

from __future__ import annotations

from pathlib import Path

from crew.agents import prodguard

from .git_helpers import make_git_repo

GLOBS = ("tests/**", "**/test_*.py")


def test_snapshot_ignores_tests_and_detects_production_changes(tmp_path: Path) -> None:
    repo = make_git_repo(tmp_path / "repo")
    before = prodguard.snapshot(repo, GLOBS)
    assert before and not any(rel.startswith("tests/") for rel in before)

    (repo / "tests").mkdir(exist_ok=True)
    (repo / "tests" / "test_x.py").write_text("x", "utf-8")
    (repo / "pkg").mkdir()
    (repo / "pkg" / "test_y.py").write_text("y", "utf-8")
    assert prodguard.changed(before, prodguard.snapshot(repo, GLOBS)) == []

    (repo / "novo.py").write_text("z", "utf-8")
    first = next(iter(before))
    (repo / first).write_text("edited", "utf-8")
    assert prodguard.changed(before, prodguard.snapshot(repo, GLOBS)) == sorted([first, "novo.py"])


def test_describe_lists_a_bounded_number_of_files() -> None:
    text = prodguard.describe([f"f{i}.py" for i in range(10)], limit=3)
    assert text.startswith("o Tester alterou código de produção: f0.py, f1.py, f2.py (+7)")


def test_the_plan_doc_is_dev_crews_own_file(tmp_path: Path) -> None:
    # dev-crew may rewrite it while a Tester runs in the task worktree (D57, D68)
    repo = make_git_repo(tmp_path)
    (repo / "docs" / "plano").mkdir(parents=True)
    (repo / "docs" / "plano" / "T-1.md").write_text("v1", "utf-8")
    before = prodguard.snapshot(repo, ())
    (repo / "docs" / "plano" / "T-1.md").write_text("v2", "utf-8")
    assert prodguard.changed(before, prodguard.snapshot(repo, ())) == []
