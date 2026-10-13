"""Matt Pocock's skills vendored into the agent prompts (D65, D66)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from crew.agents import skills
from crew.agents.context import system_prompt_text
from crew.contracts import AGENTS
from tests.git_helpers import sh_git


def test_vendored_files_match_the_lock() -> None:
    # editing a vendored file by hand breaks this: update with `crew skills sync` instead
    assert skills.verify() == []
    assert set(skills.read_lock()["files"]) == set(skills.FILES)  # type: ignore[arg-type]


def test_manifest_only_points_at_vendored_skill_files() -> None:
    for files in skills.MANIFEST.values():
        assert files and all(rel in skills.FILES and rel != "LICENSE" for rel in files)


@pytest.mark.parametrize("agent", AGENTS)
def test_every_agent_prompt_ends_with_its_skills(agent: str) -> None:
    text = system_prompt_text(agent)
    assert text.index("# Papel:") < text.index("Método: skills do Matt Pocock")
    for rel in skills.MANIFEST[agent]:
        assert f"mattpocock/skills · {rel}" in text
    assert "\n---\nname:" not in text  # frontmatter stripped


def test_skills_follow_the_manifest_per_agent() -> None:
    assert "Red before green" in system_prompt_text("developer")
    assert "Two-axis review" in system_prompt_text("reviewer")
    assert "tracer-bullet" in system_prompt_text("planner").lower()
    assert "Red before green" not in system_prompt_text("planner")


def test_strip_frontmatter() -> None:
    assert skills.strip_frontmatter("---\nname: x\n---\n\nbody\n") == "body\n"
    assert skills.strip_frontmatter("no frontmatter") == "no frontmatter"


def test_verify_flags_an_edited_file(tmp_path: Path) -> None:
    vendor = tmp_path / "matt"
    vendor.mkdir()
    (vendor / "a.md").write_text("one\n", "utf-8")
    lock = tmp_path / "lock.json"
    lock.write_text(json.dumps({"files": {"a.md": skills._sha256("one\n")}}), "utf-8")
    assert skills.verify(vendor, lock) == sorted(set(skills.FILES))  # a.md ok, manifest files missing
    (vendor / "a.md").write_text("two\n", "utf-8")
    assert "a.md" in skills.verify(vendor, lock)


def test_sync_pins_the_commit_and_copies_only_the_listed_files(tmp_path: Path) -> None:
    upstream = tmp_path / "upstream"
    for src in skills.FILES.values():
        (upstream / src).parent.mkdir(parents=True, exist_ok=True)
        (upstream / src).write_bytes(f"content of {src}\r\n".encode())
    (upstream / "skills" / "engineering" / "implement").mkdir(parents=True)
    (upstream / "skills" / "engineering" / "implement" / "SKILL.md").write_text("not listed\n", "utf-8")
    sh_git(upstream, "init", "-q", "-b", "main")
    sh_git(upstream, "add", "-A")
    sh_git(upstream, "commit", "-q", "-m", "v1")
    pinned = sh_git(upstream, "rev-parse", "HEAD")
    (upstream / "LICENSE").write_text("changed later\n", "utf-8")
    sh_git(upstream, "commit", "-q", "-am", "v2")

    vendor, lock = tmp_path / "vendor", tmp_path / "vendor" / "lock.json"
    commit = skills.sync(pinned, upstream=str(upstream), vendor_dir=vendor, lock_file=lock)

    assert commit == pinned
    assert (vendor / "LICENSE").read_text("utf-8") == "content of LICENSE\n"  # pinned, LF
    assert not (vendor / "implement").exists()
    assert skills.read_lock(lock)["commit"] == pinned
    assert skills.verify(vendor, lock) == []


def test_sync_fails_when_upstream_lost_a_file(tmp_path: Path) -> None:
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    (upstream / "LICENSE").write_text("MIT\n", "utf-8")
    sh_git(upstream, "init", "-q", "-b", "main")
    sh_git(upstream, "add", "-A")
    sh_git(upstream, "commit", "-q", "-m", "v1")
    with pytest.raises(skills.SkillsSyncError, match="sumiram"):
        skills.sync("main", upstream=str(upstream), vendor_dir=tmp_path / "v", lock_file=tmp_path / "l.json")
