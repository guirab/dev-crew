"""Host side of the standards job (D82): the vault copy the agent reads and the base it writes.

Before the job, the ``.md`` notes of the vault are copied to ``<worktree>/.crew/vault/`` (the agent cannot
read outside the worktree) and ``<worktree>/.crew/standards-out/`` is created for its output. After it,
the valid files of the output go to ``<vault>/standards/`` (the vault is created when missing; a file
that changes is first kept in ``<vault>/.dev-crew-backup/<timestamp>/``) and ``.crew/`` is removed.
``.crew/`` is in the repo's ``info/exclude``: it never shows up in a diff or commit.
"""

from __future__ import annotations

import re
import shutil
from datetime import UTC, datetime
from pathlib import Path

import structlog

from ..vaults import CREW_DIR, STANDARDS_OUT, VAULT_COPY, VaultInfo
from . import git

log = structlog.get_logger(__name__)

MAX_FILES = 500
MAX_FILE_BYTES = 512 * 1024
MAX_TOTAL_BYTES = 8 * 1024 * 1024
EXCLUDE_LINE = f"/{CREW_DIR}/"
BACKUP_DIR = ".dev-crew-backup"  # hidden: Obsidian and the vault copy (``_vault_notes``) skip it

BEFORE = "Before You Develop.md"
_PROJECT_FILES = frozenset({"Glossary.md", "Conventions.md"})
_REPO_FILES = frozenset({BEFORE, "Conventions.md"})
_ADR = re.compile(r"ADR-\d{4} - [^/\\]+\.md")


class VaultIOError(RuntimeError):
    """The standards base could not be written. The message is shown to the user (pt-BR)."""


def cleanup(worktree: Path) -> None:
    shutil.rmtree(worktree / CREW_DIR, ignore_errors=True)


def _vault_notes(vault: Path) -> list[Path]:
    """The vault's ``.md`` files, ``standards/`` first; hidden folders (``.obsidian``, ``.trash``) skipped."""
    found = [
        p
        for p in vault.rglob("*.md")
        if p.is_file()
        and not p.is_symlink()
        and not any(part.startswith(".") for part in p.relative_to(vault).parts)
    ]
    return sorted(found, key=lambda p: (p.relative_to(vault).parts[0].lower() != "standards", p.as_posix()))


def stage(worktree: Path, vault: Path) -> int:
    """A fresh ``.crew/vault`` (the vault's notes, within the caps) and an empty ``.crew/standards-out``."""
    cleanup(worktree)
    (worktree / STANDARDS_OUT).mkdir(parents=True)
    dest = worktree / VAULT_COPY
    dest.mkdir(parents=True)
    if not vault.is_dir():
        return 0
    copied = total = 0
    skipped: list[str] = []
    for src in _vault_notes(vault):
        rel = src.relative_to(vault)
        size = src.stat().st_size
        if copied >= MAX_FILES or size > MAX_FILE_BYTES or total + size > MAX_TOTAL_BYTES:
            skipped.append(rel.as_posix())
            continue
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, target)
        copied += 1
        total += size
    if skipped:
        log.warning("vault_copy_truncated", vault=str(vault), copied=copied, skipped=len(skipped))
    return copied


async def exclude_crew_dir(worktree: Path) -> None:
    """Add ``/.crew/`` to the repo's ``info/exclude`` (shared by its worktrees), once."""
    raw = await git.out(worktree, "rev-parse", "--git-path", "info/exclude")
    path = Path(raw) if Path(raw).is_absolute() else worktree / raw
    text = path.read_text("utf-8") if path.is_file() else ""
    if EXCLUDE_LINE in text.splitlines():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    sep = "" if not text or text.endswith("\n") else "\n"
    path.write_text(f"{text}{sep}{EXCLUDE_LINE}\n", encoding="utf-8")


def _allowed(rel: str, info: VaultInfo) -> bool:
    """Only the files FORMATS.md defines, in the repo's layout."""
    parts = rel.split("/")
    project = _PROJECT_FILES | ({BEFORE} if info.layout == "single" else set())
    if len(parts) == 1:
        return parts[0] in project
    if len(parts) == 2 and parts[0] == "decisions":
        return bool(_ADR.fullmatch(parts[1]))
    in_repo = len(parts) == 2 and parts[0] == info.repo and parts[1] in _REPO_FILES
    return info.layout == "workspace" and in_repo


def _is_text(path: Path) -> bool:
    try:
        path.read_text("utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    return True


def output_files(worktree: Path, info: VaultInfo) -> list[str]:
    """What the agent wrote that may go to the vault (relative to ``standards/``); the rest is logged."""
    out = worktree / STANDARDS_OUT
    if not out.is_dir():
        return []
    keep: list[str] = []
    dropped: list[str] = []
    for path in sorted(out.rglob("*")):
        if path.is_dir() and not path.is_symlink():
            continue
        rel = path.relative_to(out).as_posix()
        ok = (
            not path.is_symlink()
            and path.is_file()
            and path.stat().st_size <= MAX_FILE_BYTES
            and _allowed(rel, info)
            and _is_text(path)
        )
        (keep if ok else dropped).append(rel)
    if dropped:
        log.warning("standards_output_dropped", files=sorted(dropped))
    return sorted(keep)


def home_note(info: VaultInfo) -> str:
    """``Home.md`` of a vault created by dev-crew (FORMATS.md template)."""
    if info.layout == "workspace":
        entry = f"[[standards/{info.repo}/Before You Develop|{info.repo}]]"
    else:
        entry = "[[standards/Before You Develop|Before You Develop]]"
    return (
        f"# {info.project}\n\n"
        "Standards base created by dev-crew.\n\n"
        "## Standards\n\n"
        "- [[standards/Glossary|Glossary]]\n"
        "- [[standards/Conventions|Conventions]]\n"
        f"- {entry}\n"
    )


def create_vault(info: VaultInfo) -> None:
    """An empty ``.obsidian/`` (what makes Obsidian see a vault) and ``Home.md``."""
    (info.vault / ".obsidian").mkdir(parents=True, exist_ok=True)
    home = info.vault / "Home.md"
    if not home.exists():
        home.write_text(home_note(info), encoding="utf-8")
    log.info("vault_created", vault=str(info.vault))


def publish(worktree: Path, info: VaultInfo) -> list[str]:
    """Copy the agent's base into the vault (creating it when missing). Returns the files written."""
    files = output_files(worktree, info)
    if not files:
        raise VaultIOError("o agente não escreveu nenhum arquivo válido da base")
    if not info.vault.is_dir():
        create_vault(info)
    out = worktree / STANDARDS_OUT
    backup = info.vault / BACKUP_DIR / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    for rel in files:
        target = info.root / rel
        if target.is_file() and target.read_bytes() != (out / rel).read_bytes():
            # project-level files are rewritten by the agent: keep the old one in case it dropped content
            kept = backup / target.relative_to(info.vault)
            kept.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(target, kept)
            log.warning("standards_backup", file=str(target), backup=str(kept))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(out / rel, target)
    log.info("standards_published", root=str(info.root), files=len(files))
    return files


def write_fake_base(worktree: Path, repo: str) -> list[str]:
    """Fake agents only: a minimal single-repo base in ``.crew/standards-out/`` (what a real job writes).

    With ``--fake-agents`` the orchestrator sends it to ``CREW_HOME/fake-vaults``, never a real vault.
    """
    files = {
        BEFORE: f"# Before You Develop: {repo}\n\nFake base written by dev-crew's fake agents.\n",
        "Conventions.md": "# Conventions\n\n## Testing\n\nEvery change ships with a test.\n",
        "Glossary.md": f"# Glossary\n\n**{repo}**:\nThe repository under work.\n",
    }
    out = worktree / STANDARDS_OUT
    out.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (out / name).write_text(text, encoding="utf-8")
    return list(files)
