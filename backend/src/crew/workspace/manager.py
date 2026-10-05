"""Per-task git workspace: worktree on ``crew/<task_id>``, diff report, cleanup. Nothing is ever committed."""

from __future__ import annotations

import asyncio
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import structlog

from .. import sandbox
from ..config import RepoCfg
from ..contracts import FileChange, FinalFile
from . import git

log = structlog.get_logger(__name__)

WorkspaceMode = Literal["worktree", "inplace"]
TASK_ID_RE = re.compile(r"^T-\d+$")
MAX_COUNTED_BYTES = 5 * 1024 * 1024
FETCH_TIMEOUT_S = 30.0


class WorkspaceError(RuntimeError):
    """Pre-condition failed or git refused. The message is shown to the user (pt-BR)."""


class WorkspaceDirty(WorkspaceError):
    """Cleanup refused: the worktree has uncommitted changes."""


@dataclass(frozen=True)
class Workspace:
    task_id: str
    repo_name: str
    repo_path: Path
    path: Path
    branch: str
    base_branch: str
    mode: WorkspaceMode


class WorkspaceManager:
    def __init__(self, root: Path, mode: WorkspaceMode = "worktree", *, fetch: bool = True) -> None:
        self.root = root
        self.mode: WorkspaceMode = mode
        self.fetch = fetch

    # ------------------------------------------------------------------ locate

    def locate(self, task_id: str, repo: RepoCfg) -> Workspace:
        """Deterministic location of a task's workspace (no I/O)."""
        if not TASK_ID_RE.fullmatch(task_id):
            raise WorkspaceError(f"id de tarefa inválido: {task_id!r} (esperado T-<n>)")
        if Path(repo.name).name != repo.name or repo.name in {"", ".", ".."}:
            raise WorkspaceError(f"nome de repositório inválido para worktree: {repo.name!r}")
        if self.mode == "inplace":
            return Workspace(task_id, repo.name, repo.path, repo.path, "", repo.base_branch, "inplace")
        return Workspace(
            task_id=task_id,
            repo_name=repo.name,
            repo_path=repo.path,
            path=self.root / repo.name / task_id,
            branch=f"crew/{task_id}",
            base_branch=repo.base_branch,
            mode="worktree",
        )

    def find(self, task_id: str) -> list[Path]:
        """Worktree directories named ``task_id`` under ``<root>/<repo>/`` (used by ``crew cleanup``)."""
        if not TASK_ID_RE.fullmatch(task_id) or not self.root.is_dir():
            return []
        return sorted(p for p in self.root.glob(f"*/{task_id}") if p.is_dir())

    # ------------------------------------------------------------------ create

    async def create(self, task_id: str, repo: RepoCfg) -> Workspace:
        ws = self.locate(task_id, repo)
        repo_path = repo.path
        if not repo_path.is_dir():
            raise WorkspaceError(f"repositório não encontrado: {repo_path}")
        if not await git.ok(repo_path, "rev-parse", "--git-dir"):
            raise WorkspaceError(f"{repo_path} não é um repositório git")
        if not await git.ok(repo_path, "rev-parse", "--verify", "--quiet", f"{repo.base_branch}^{{commit}}"):
            raise WorkspaceError(f"branch base {repo.base_branch!r} não existe em {repo_path}")

        if ws.mode == "inplace":
            return await self._create_inplace(ws)
        return await self._create_worktree(ws)

    async def _create_inplace(self, ws: Workspace) -> Workspace:
        if await git.out(ws.repo_path, "status", "--porcelain"):
            raise WorkspaceError(f"modo inplace exige working tree limpo em {ws.repo_path}")
        branch = await git.out(ws.repo_path, "rev-parse", "--abbrev-ref", "HEAD")
        return Workspace(
            ws.task_id, ws.repo_name, ws.repo_path, ws.repo_path, branch, ws.base_branch, "inplace"
        )

    async def _create_worktree(self, ws: Workspace) -> Workspace:
        if ws.path.exists():
            # idempotent: the orchestrator may re-issue CreateWorkspace after a restart
            if await self._is_worktree_on_branch(ws):
                log.info("workspace_reused", task_id=ws.task_id, path=str(ws.path))
                return ws
            raise WorkspaceError(f"{ws.path} já existe e não é o worktree de {ws.branch}")
        await git.run(ws.repo_path, "worktree", "prune", check=False)
        if await git.ok(ws.repo_path, "show-ref", "--verify", "--quiet", f"refs/heads/{ws.branch}"):
            raise WorkspaceError(f"branch {ws.branch} já existe em {ws.repo_path}")

        if self.fetch and await git.out(ws.repo_path, "remote"):
            res = await git.run(ws.repo_path, "fetch", "--quiet", timeout=FETCH_TIMEOUT_S, check=False)
            if res.returncode != 0:  # offline is fine
                log.info("fetch_skipped", task_id=ws.task_id, stderr=res.stderr.strip()[:200])

        ws.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            await git.run(ws.repo_path, "worktree", "add", str(ws.path), "-b", ws.branch, ws.base_branch)
        except git.GitError as e:
            raise WorkspaceError(f"não consegui criar o worktree: {e.stderr}") from e
        if await git.out(ws.path, "status", "--porcelain"):
            raise WorkspaceError(f"worktree recém-criado não está limpo: {ws.path}")
        log.info("workspace_created", task_id=ws.task_id, path=str(ws.path), branch=ws.branch)
        return ws

    # ------------------------------------------------------------------ environment

    async def prepare(self, ws: Workspace, repo: RepoCfg) -> None:
        """Make the workspace runnable before any agent: sandbox container and/or ``setup_cmd``.

        Raises ``WorkspaceError`` (setup or Docker failed): the task fails before spending tokens.
        """
        try:
            if repo.sandbox_image:
                layout = await git_layout(ws.path)
                name = await sandbox.create(
                    ws.task_id, repo.name, repo.sandbox_image, ws.path, layout, tuple(repo.deps_dirs)
                )
                await sandbox.setup(name, repo.setup_cmd)
            elif repo.setup_cmd:
                await run_host_setup(ws.path, repo.setup_cmd)
        except sandbox.SandboxError as e:
            raise WorkspaceError(str(e)) from e

    async def _is_worktree_on_branch(self, ws: Workspace) -> bool:
        res = await git.run(ws.path, "rev-parse", "--abbrev-ref", "HEAD", check=False)
        return res.returncode == 0 and res.stdout.strip() == ws.branch

    # ------------------------------------------------------------------ diff report

    async def diff_report(self, ws: Workspace) -> list[FinalFile]:
        """Files changed vs the base branch, including untracked ones, sorted by path."""
        base = await self._diff_base(ws)
        status = await git.run(ws.path, "status", "--porcelain=v1", "-z", "-uall", "--no-renames")
        numstat = await git.run(ws.path, "diff", "--numstat", "-z", "--no-renames", base)
        counts = _parse_numstat(numstat.stdout)

        files: list[FinalFile] = []
        for xy, rel in _parse_status(status.stdout):
            change = _change_of(xy)
            if xy == "??":
                added, removed = _count_untracked(ws.path / rel), 0
            elif rel in counts:
                added, removed = counts[rel]
            else:  # e.g. intent-to-add: not in the diff yet
                added, removed = (_count_untracked(ws.path / rel), 0) if change == "A" else (0, 0)
            files.append(FinalFile(path=rel, status=change, added=added, removed=removed))
        return sorted(files, key=lambda f: f.path)

    async def _diff_base(self, ws: Workspace) -> str:
        res = await git.run(ws.path, "merge-base", "HEAD", ws.base_branch, check=False)
        sha = res.stdout.strip()
        return sha if res.returncode == 0 and sha else ws.base_branch

    # ------------------------------------------------------------------ cleanup

    async def cleanup(self, ws: Workspace, *, force: bool = False) -> None:
        """Remove the worktree and its (empty) branch. Refuses when there are uncommitted changes."""
        if ws.mode == "inplace":
            raise WorkspaceError("modo inplace: não há worktree para remover")
        if not ws.path.exists():
            await git.run(ws.repo_path, "worktree", "prune", check=False)
            return
        if not force and await git.out(ws.path, "status", "--porcelain"):
            raise WorkspaceDirty(f"{ws.path} tem mudanças não commitadas; commite/descarte ou use --force")
        args = ["worktree", "remove", str(ws.path)]
        if force:
            args.insert(2, "--force")
        try:
            await git.run(ws.repo_path, *args)
        except git.GitError as e:
            raise WorkspaceError(f"não consegui remover o worktree: {e.stderr}") from e
        # -d only deletes when merged (i.e. nothing of value lost); -D when the user insists
        res = await git.run(ws.repo_path, "branch", "-D" if force else "-d", ws.branch, check=False)
        if res.returncode != 0:
            log.warning("branch_kept", branch=ws.branch, stderr=res.stderr.strip()[:200])
        log.info("workspace_removed", task_id=ws.task_id, path=str(ws.path))


# ---------------------------------------------------------------------- environment helpers


async def git_layout(path: Path) -> sandbox.GitLayout:
    """Host location of the worktree's git data, for the read-only mount in the sandbox."""
    common = Path(await git.out(path, "rev-parse", "--git-common-dir"))
    git_dir = Path(await git.out(path, "rev-parse", "--absolute-git-dir"))
    crlf = await git.run(path, "config", "--get", "core.autocrlf", check=False)
    return _layout(path, common, git_dir, crlf.stdout.strip() or None)


def _layout(path: Path, common: Path, git_dir: Path, autocrlf: str | None) -> sandbox.GitLayout:
    # normpath is lexical (no I/O): rev-parse may answer the common dir relative to the worktree
    return sandbox.GitLayout(
        common_dir=Path(os.path.normpath(common if common.is_absolute() else path / common)),
        git_dir=Path(os.path.normpath(git_dir)),
        autocrlf=autocrlf,
    )


async def run_host_setup(path: Path, command: str) -> None:
    """``setup_cmd`` without a sandbox: run by dev-crew in the worktree, through the system shell."""

    def run() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            shell=True,
            cwd=path,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=sandbox.SETUP_TIMEOUT_S,
            check=False,
        )

    try:
        res = await asyncio.to_thread(run)
    except subprocess.TimeoutExpired as e:
        raise WorkspaceError(f"setup (`{command}`) passou de {sandbox.SETUP_TIMEOUT_S:.0f}s") from e
    if res.returncode != 0:
        output = (res.stdout + res.stderr).strip()
        raise WorkspaceError(f"setup falhou (`{command}`, código {res.returncode}):\n{sandbox.tail(output)}")
    log.info("setup_done", path=str(path))


# ---------------------------------------------------------------------- parsing helpers


def _parse_status(raw: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for entry in raw.split("\0"):
        if len(entry) > 3:
            out.append((entry[:2], entry[3:]))
    return out


def _parse_numstat(raw: str) -> dict[str, tuple[int, int]]:
    counts: dict[str, tuple[int, int]] = {}
    for entry in raw.split("\0"):
        parts = entry.split("\t", 2)
        if len(parts) != 3:
            continue
        added, removed, path = parts
        counts[path] = (int(added) if added.isdigit() else 0, int(removed) if removed.isdigit() else 0)
    return counts


def _change_of(xy: str) -> FileChange:
    if xy == "??":
        return "A"
    if "D" in xy:
        return "D"
    if "A" in xy:
        return "A"
    return "M"


def _count_untracked(path: Path) -> int:
    """Line count of a new file; 0 for binaries, symlinks, directories and huge files."""
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_COUNTED_BYTES:
            return 0
        data = path.read_bytes()
    except OSError:
        return 0
    if b"\0" in data[:8000]:
        return 0
    return data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)
