"""Where a repo's Obsidian vault and standards base live (D82). Filesystem reads only, no writes.

Convention (same as the ``project-standards`` skill): code repos hold only code; every ``.md`` of a project
lives in ``~/Documents/Vaults/<vault>/``. The base goes in ``<vault>/standards/`` (single-repo project) or
``<vault>/standards/<REPO>/`` plus shared files one level up (workspace project).

Order: the repo's ``standards_dir`` in the config, a ``.obsidian-vault`` file (repo root, then the workspace
folder), ``<VAULTS_ROOT>/<PROJECT>-vault``, ``<VAULTS_ROOT>/<PROJECT>``; none: the vault to create is
``<VAULTS_ROOT>/<PROJECT>-vault``. Cheap enough to run on every job.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import structlog

log = structlog.get_logger(__name__)

VAULTS_ROOT_ENV = "CREW_VAULTS_ROOT"
LINK_FILE = ".obsidian-vault"
STANDARDS = "standards"
# the standards job's folders inside the worktree (paths relative to it, POSIX)
CREW_DIR = ".crew"
VAULT_COPY = f"{CREW_DIR}/vault"  # read-only copy of the vault's notes
STANDARDS_OUT = f"{CREW_DIR}/standards-out"  # the only place the agent writes
DOCUMENTS = ("Documents", "Documentos")

Layout = Literal["single", "workspace"]


@dataclass(frozen=True)
class VaultInfo:
    vault: Path
    layout: Layout
    project: str
    repo: str  # the code repo's folder name (``<REPO>``)
    standards_dir: Path  # the repo's folder in the base: what the agents read
    exists: bool  # the vault folder exists (False: dev-crew creates it after the standards job)

    @property
    def root(self) -> Path:
        """The base's ``standards/`` folder (project level in a workspace)."""
        return self.standards_dir.parent if self.layout == "workspace" else self.standards_dir


def _same(a: Path, b: Path) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def _is_git_repo(path: Path) -> bool:
    return (path / ".git").exists()


def is_workspace(repo: Path, home: Path | None = None) -> bool:
    """The repo's parent holds other git repos. Repos loose in ``~/Documents`` (or the home) never are."""
    home = home or Path.home()
    parent = repo.parent
    if any(_same(parent, p) for p in (home, *(home / d for d in DOCUMENTS))):
        return False
    try:
        return any(p.is_dir() and not _same(p, repo) and _is_git_repo(p) for p in parent.iterdir())
    except OSError:
        return False


def _child(folder: Path, name: str) -> Path | None:
    """``folder/name`` compared case-insensitively, if it exists as a directory."""
    try:
        return next((p for p in folder.iterdir() if p.is_dir() and p.name.lower() == name.lower()), None)
    except OSError:
        return None


def vaults_roots(home: Path | None = None) -> list[Path]:
    """Where vaults are looked for, best first. ``CREW_VAULTS_ROOT`` wins (tests, sandboxed runs)."""
    env = os.environ.get(VAULTS_ROOT_ENV)
    if env:
        return [Path(env).expanduser()]
    home = home or Path.home()
    found = [v for d in DOCUMENTS if (docs := _child(home, d)) and (v := _child(docs, "vaults"))]
    if found:
        return found
    docs = _child(home, "Documents") or _child(home, "Documentos") or home / "Documents"
    return [docs / "Vaults"]


def _linked(folder: Path) -> Path | None:
    link = folder / LINK_FILE
    try:
        text = link.read_text("utf-8").strip() if link.is_file() else ""
    except (OSError, UnicodeDecodeError) as e:
        log.warning("vault_link_unreadable", path=str(link), error=str(e))
        return None
    if not text:
        return None
    target = Path(text).expanduser()
    return target if target.is_absolute() else folder / target


def _from_override(dir: Path, repo: str) -> VaultInfo:
    """``standards_dir`` from the config: ``.../standards`` (single) or ``.../standards/<REPO>``."""
    workspace = dir.name.lower() != STANDARDS and dir.parent.name.lower() == STANDARDS
    root = dir.parent if workspace else dir
    vault = root.parent
    return VaultInfo(
        vault=vault,
        layout="workspace" if workspace else "single",
        project=vault.name.removesuffix("-vault"),
        repo=repo,
        standards_dir=dir,
        exists=vault.is_dir(),
    )


def resolve(
    repo: Path,
    standards_dir: Path | None = None,
    *,
    roots: Sequence[Path] | None = None,
    links: bool = True,
    home: Path | None = None,
) -> VaultInfo:
    """The vault of the code repo at ``repo``. ``links=False`` skips ``.obsidian-vault`` (sandboxed runs)."""
    name = repo.name
    if standards_dir is not None:
        return _from_override(standards_dir, name)
    workspace = is_workspace(repo, home)
    project = repo.parent.name if workspace else name
    vault: Path | None = None
    if links:
        vault = _linked(repo) or (_linked(repo.parent) if workspace else None)
    candidates = list(roots) if roots is not None else vaults_roots(home)
    if vault is None:
        for root in candidates:
            vault = _child(root, f"{project}-vault") or _child(root, project)
            if vault is not None:
                break
    if vault is None:
        vault = candidates[0] / f"{project}-vault"
    base = vault / STANDARDS
    return VaultInfo(
        vault=vault,
        layout="workspace" if workspace else "single",
        project=project,
        repo=name,
        standards_dir=base / name if workspace else base,
        exists=vault.is_dir(),
    )
