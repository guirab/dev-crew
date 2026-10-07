"""Read-only folder browsing for "add an existing repository" (GET /api/folders).

Nothing here writes to disk. Windows-only pieces (drive letters, HIDDEN/SYSTEM attributes) live in small
functions that tests replace, so they never break the Linux test run.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from .config import CrewConfig
from .contracts import FolderEntry, FolderListing, FolderProbe, GitState
from .workspace import git

FILE_ATTRIBUTE_HIDDEN = 0x2
FILE_ATTRIBUTE_SYSTEM = 0x4


class FolderError(RuntimeError):
    """Bad folder request. The message is meant for the end user (pt-BR)."""


# ------------------------------------------------------------------ paths


def norm_path(path: str | Path) -> str:
    """Comparable form of a path: absolute, symlinks resolved, case-folded and slash-normalized on Windows."""
    return os.path.normcase(str(Path(path).resolve()))


def is_registered_path(cfg: CrewConfig, path: str | Path) -> bool:
    wanted = norm_path(path)
    return any(norm_path(r.path) == wanted for r in cfg.repos)


def check_folder(path: str) -> Path:
    """The absolute, existing folder behind ``path``; ``FolderError`` otherwise."""
    if not path.strip() or not Path(path).is_absolute():
        raise FolderError(f"o caminho precisa ser absoluto: {path!r}")
    try:
        resolved = Path(path).resolve(strict=True)
    except OSError:
        raise FolderError(f"a pasta não existe: {path}") from None
    if not resolved.is_dir():
        raise FolderError(f"não é uma pasta: {path}")
    return resolved


# ------------------------------------------------------------------ listing


def _windows() -> bool:
    return sys.platform == "win32"


def list_drives() -> list[str]:
    """Roots of the file system: the drive letters on Windows, ``/`` elsewhere."""
    if sys.platform == "win32":
        return list(os.listdrives())
    return ["/"]


def _hidden_by_system(entry: os.DirEntry[str]) -> bool:
    attrs = getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0)
    return bool(attrs & (FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM))


def _can_open(path: str) -> bool:
    try:
        with os.scandir(path):
            return True
    except OSError:
        return False


def _subfolders(folder: Path) -> list[os.DirEntry[str]]:
    try:
        with os.scandir(folder) as it:
            found = list(it)
    except OSError:
        raise FolderError(f"não consegui ler a pasta: {folder}") from None
    keep: list[os.DirEntry[str]] = []
    for entry in found:
        if entry.name.startswith("."):
            continue
        try:
            if not entry.is_dir(follow_symlinks=False) or _hidden_by_system(entry):
                continue
        except OSError:
            continue
        if _can_open(entry.path):
            keep.append(entry)
    return sorted(keep, key=lambda e: e.name.casefold())


def list_folders(path: str | None, cfg: CrewConfig) -> FolderListing:
    """Sub-folders of ``path`` (``None``: the projects folder; ``""``: the drives level)."""
    if path is None:
        path = str(cfg.workspace.projects_dir)
    if path == "" and _windows():
        drives = [
            FolderEntry(name=d.rstrip("\\/"), path=d, git_repo=False, registered=False) for d in list_drives()
        ]
        return FolderListing(path="", parent=None, entries=drives)
    folder = check_folder(path or list_drives()[0])
    parent = folder.parent
    if parent == folder:
        top = "" if _windows() else None
    else:
        top = str(parent)
    registered = {norm_path(r.path) for r in cfg.repos}
    entries = [
        FolderEntry(
            name=e.name,
            path=str(folder / e.name),
            git_repo=os.path.lexists(os.path.join(e.path, ".git")),
            registered=norm_path(folder / e.name) in registered,
        )
        for e in _subfolders(folder)
    ]
    return FolderListing(path=str(folder), parent=top, entries=entries)


# ------------------------------------------------------------------ probe


async def probe(path: str, cfg: CrewConfig) -> FolderProbe:
    """What git says about ``path``: not a repo, a repo without commits, ready, or inside another repo."""
    folder = check_folder(path)
    state: GitState = "none"
    branch: str | None = None
    top = await git.run(folder, "rev-parse", "--show-toplevel", check=False)
    if top.returncode == 0 and top.stdout.strip():
        if norm_path(top.stdout.strip()) != norm_path(folder):
            state = "inside_repo"
        else:
            has_commit = await git.ok(folder, "rev-parse", "--verify", "--quiet", "HEAD^{commit}")
            state = "ready" if has_commit else "empty"
            head = await git.run(folder, "symbolic-ref", "--short", "-q", "HEAD", check=False)
            branch = (head.stdout.strip() or None) if head.returncode == 0 else None
    return FolderProbe(
        path=str(folder),
        name=folder.name or str(folder),
        git=state,
        branch=branch,
        registered=is_registered_path(cfg, folder),
    )
