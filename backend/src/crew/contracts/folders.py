"""Folder browsing for "add an existing repository" (GET /api/folders, read-only)."""

from typing import Literal

from .common import Contract

GitState = Literal["none", "empty", "ready", "inside_repo"]


class FolderEntry(Contract):
    name: str
    path: str
    git_repo: bool  # has a .git entry
    registered: bool  # already one of the configured repositories (by path)


class FolderListing(Contract):
    """Sub-folders of ``path``. ``path`` is empty at the drives level; ``parent`` is ``None`` at the top."""

    path: str
    parent: str | None = None
    entries: list[FolderEntry]


class FolderProbe(Contract):
    """What git says about one folder: ``none`` (not a repo), ``empty`` (no commit), ``ready``,
    ``inside_repo`` (a sub-folder of another repository)."""

    path: str
    name: str
    git: GitState
    branch: str | None = None
    registered: bool
