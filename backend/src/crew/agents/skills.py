"""Matt Pocock's skills inside the agents' system prompts (D65, option B).

``crew skills sync`` copies a pinned set of ``mattpocock/skills`` files into ``prompts/matt/`` and writes
``skills.lock.json`` (upstream commit + sha256 per file). At runtime nothing is fetched: each agent's
system prompt gets the dev-crew overrides (``prompts/_matt.md``) followed by the bodies of its skills,
verbatim, so the method is in context on every job and the ``Skill`` tool stays disallowed.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from functools import cache
from pathlib import Path

UPSTREAM = "https://github.com/mattpocock/skills.git"
PROMPTS_DIR = Path(__file__).parent / "prompts"
VENDOR_DIR = PROMPTS_DIR / "matt"
LOCK_FILE = VENDOR_DIR / "skills.lock.json"
OVERRIDES_FILE = PROMPTS_DIR / "_matt.md"

# vendored path (under VENDOR_DIR) -> path in the upstream repo
FILES: dict[str, str] = {
    "LICENSE": "LICENSE",
    "grilling/SKILL.md": "skills/productivity/grilling/SKILL.md",
    "domain-modeling/SKILL.md": "skills/engineering/domain-modeling/SKILL.md",
    "to-tickets/SKILL.md": "skills/engineering/to-tickets/SKILL.md",
    "codebase-design/SKILL.md": "skills/engineering/codebase-design/SKILL.md",
    "tdd/SKILL.md": "skills/engineering/tdd/SKILL.md",
    "tdd/tests.md": "skills/engineering/tdd/tests.md",
    "tdd/mocking.md": "skills/engineering/tdd/mocking.md",
    "code-review/SKILL.md": "skills/engineering/code-review/SKILL.md",
}

_TDD = ("tdd/SKILL.md", "tdd/tests.md", "tdd/mocking.md")

# D66: which vendored files each agent reads, in order
MANIFEST: dict[str, tuple[str, ...]] = {
    "interviewer": ("grilling/SKILL.md", "domain-modeling/SKILL.md"),
    "planner": ("to-tickets/SKILL.md", "codebase-design/SKILL.md"),
    "developer": _TDD,
    "tester": _TDD,
    "reviewer": ("code-review/SKILL.md", "codebase-design/SKILL.md"),
}


class SkillsSyncError(RuntimeError):
    """``crew skills sync`` failed. The message is shown to the user (pt-BR)."""


def _text(path: Path) -> str:
    # LF on every platform, so the hash does not depend on core.autocrlf
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def strip_frontmatter(text: str) -> str:
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            return text[end + 5 :].lstrip("\n")
    return text


@cache
def skills_text(agent: str) -> str:
    """Overrides + the agent's skill bodies, or ``""`` for an agent without skills."""
    files = MANIFEST.get(agent)
    if not files:
        return ""
    parts = [_text(OVERRIDES_FILE).strip()]
    for rel in files:
        body = strip_frontmatter(_text(VENDOR_DIR / rel)).strip()
        parts.append(f"### mattpocock/skills · {rel}\n\n{body}")
    return "\n\n".join(parts)


def read_lock(lock_file: Path = LOCK_FILE) -> dict[str, object]:
    data: dict[str, object] = json.loads(lock_file.read_text(encoding="utf-8"))
    return data


def verify(vendor_dir: Path = VENDOR_DIR, lock_file: Path = LOCK_FILE) -> list[str]:
    """Vendored files that are missing or differ from the lock (empty = all good)."""
    hashes = read_lock(lock_file)["files"]
    assert isinstance(hashes, dict)
    problems = [rel for rel in FILES if rel not in hashes]
    for rel, expected in hashes.items():
        path = vendor_dir / rel
        if not path.is_file() or _sha256(_text(path)) != expected:
            problems.append(rel)
    return sorted(problems)


def _git(*args: str, cwd: Path | None = None) -> str:
    res = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=300, check=False)
    if res.returncode != 0:
        raise SkillsSyncError(f"git {args[0]} falhou: {res.stderr.strip()}")
    return res.stdout.strip()


def sync(
    ref: str, *, upstream: str = UPSTREAM, vendor_dir: Path = VENDOR_DIR, lock_file: Path = LOCK_FILE
) -> str:
    """Copy ``FILES`` from ``upstream`` at ``ref`` into ``vendor_dir`` and rewrite the lock. Returns the SHA.

    Only copies text files: nothing from the clone is executed.
    """
    with tempfile.TemporaryDirectory(prefix="crew-skills-") as tmp:
        clone = Path(tmp) / "skills"
        _git("clone", "--quiet", upstream, str(clone))
        _git("checkout", "--quiet", "--detach", ref, cwd=clone)
        commit = _git("rev-parse", "HEAD", cwd=clone)
        missing = [src for src in FILES.values() if not (clone / src).is_file()]
        if missing:
            raise SkillsSyncError(f"arquivos sumiram do upstream em {commit[:7]}: {', '.join(missing)}")
        if vendor_dir.exists():
            shutil.rmtree(vendor_dir)
        hashes: dict[str, str] = {}
        for rel, src in FILES.items():
            text = _text(clone / src)
            dest = vendor_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(text, encoding="utf-8", newline="\n")
            hashes[rel] = _sha256(text)
    lock = {"upstream": upstream, "commit": commit, "files": hashes}
    lock_file.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8", newline="\n")
    skills_text.cache_clear()
    return commit
