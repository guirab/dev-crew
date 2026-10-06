"""Per-task git workspace: worktree on ``crew/<task_id>``, diff report, cleanup.

A single execution never commits. A split plan (D54) gives each epic its own worktree on
``crew/<task>-<epic>``, started from the task branch; dev-crew (never an agent) commits the approved epic
and merges it into the task branch. A conflicting merge stays in progress in the task worktree for the
integration lane to resolve (D55).
"""

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
EPIC_ID_RE = re.compile(r"^E\d+$")
CREW_AUTHOR = ("-c", "user.name=dev-crew", "-c", "user.email=dev-crew@localhost")
PLAN_DOC_DIR = "docs/plano"
MAX_COUNTED_BYTES = 5 * 1024 * 1024
FETCH_TIMEOUT_S = 30.0


class WorkspaceError(RuntimeError):
    """Pre-condition failed or git refused. The message is shown to the user (pt-BR)."""


class WorkspaceDirty(WorkspaceError):
    """Cleanup refused: the worktree has uncommitted changes."""


@dataclass(frozen=True)
class MergeOutcome:
    """``sha`` of the merge commit, or the conflicted files (merge left in progress for the integrator)."""

    sha: str | None
    conflicts: tuple[str, ...] = ()


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

    def locate_epic(self, task: Workspace, epic_id: str) -> Workspace:
        """Worktree of one epic, started from the task branch (no I/O)."""
        if task.mode != "worktree":
            raise WorkspaceError('plano dividido em épicos exige workspace.mode = "worktree"')
        if not EPIC_ID_RE.fullmatch(epic_id):
            raise WorkspaceError(f"id de épico inválido: {epic_id!r}")
        lane = f"{task.task_id}-{epic_id}"
        return Workspace(
            task_id=lane,
            repo_name=task.repo_name,
            repo_path=task.repo_path,
            path=self.root / task.repo_name / lane,
            branch=f"crew/{lane}",
            base_branch=task.branch,
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
        return await self._create_worktree(ws, fetch=self.fetch)

    async def create_epic(self, task: Workspace, epic_id: str) -> Workspace:
        """Worktree of an epic from the current task branch (it already has the epics it depends on)."""
        return await self._create_worktree(self.locate_epic(task, epic_id), fetch=False)

    async def _create_inplace(self, ws: Workspace) -> Workspace:
        if await git.out(ws.repo_path, "status", "--porcelain"):
            raise WorkspaceError(f"modo inplace exige working tree limpo em {ws.repo_path}")
        branch = await git.out(ws.repo_path, "rev-parse", "--abbrev-ref", "HEAD")
        return Workspace(
            ws.task_id, ws.repo_name, ws.repo_path, ws.repo_path, branch, ws.base_branch, "inplace"
        )

    async def _create_worktree(self, ws: Workspace, *, fetch: bool) -> Workspace:
        if ws.path.exists():
            # idempotent: the orchestrator may re-issue CreateWorkspace after a restart
            if await self._is_worktree_on_branch(ws):
                log.info("workspace_reused", task_id=ws.task_id, path=str(ws.path))
                return ws
            raise WorkspaceError(f"{ws.path} já existe e não é o worktree de {ws.branch}")
        await git.run(ws.repo_path, "worktree", "prune", check=False)
        if await git.ok(ws.repo_path, "show-ref", "--verify", "--quiet", f"refs/heads/{ws.branch}"):
            raise WorkspaceError(f"branch {ws.branch} já existe em {ws.repo_path}")

        if fetch and await git.out(ws.repo_path, "remote"):
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

    # ------------------------------------------------------------------ commits / merges (D54, D55)

    async def commit_all(self, ws: Workspace, message: str) -> str | None:
        """Stage everything and commit with the user's git identity (dev-crew's when there is none).

        Returns the new sha, or ``None`` when there was nothing to commit. Repo hooks run as usual.
        """
        await git.run(ws.path, "add", "-A")
        if await git.ok(ws.path, "diff", "--cached", "--quiet"):
            return None
        await self._commit(ws.path, "commit", "-q", "-m", message)
        return await git.out(ws.path, "rev-parse", "HEAD")

    async def merge(self, task: Workspace, branch: str, message: str) -> MergeOutcome:
        """Merge ``branch`` into the task branch. A conflict is left in progress (markers in the files)."""
        res = await self._git_as_user(task.path, "merge", "--no-ff", "-m", message, branch)
        if res.returncode == 0:
            return MergeOutcome(sha=await git.out(task.path, "rev-parse", "HEAD"))
        conflicts = await git.out(task.path, "diff", "--name-only", "--diff-filter=U")
        if not conflicts:
            raise WorkspaceError(f"merge de {branch} falhou: {(res.stderr or res.stdout).strip()[:300]}")
        return MergeOutcome(sha=None, conflicts=tuple(conflicts.splitlines()))

    async def finish_merge(self, task: Workspace, message: str) -> str:
        """Conclude the merge the integration lane resolved."""
        await git.run(task.path, "add", "-A")
        markers = await git.run(task.path, "diff", "--cached", "--check", check=False)
        if "conflict marker" in markers.stdout:
            raise WorkspaceError("ainda há marcadores de conflito nos arquivos")
        await self._commit(task.path, "commit", "-q", "-m", message)
        return await git.out(task.path, "rev-parse", "HEAD")

    async def abort_merge(self, task: Workspace) -> None:
        await git.run(task.path, "merge", "--abort", check=False)

    async def remove_epic(self, epic: Workspace) -> None:
        """Drop a merged epic's worktree and branch (its commit lives on in the task branch)."""
        if epic.path.exists():
            await git.run(epic.repo_path, "worktree", "remove", "--force", str(epic.path), check=False)
        await git.run(epic.repo_path, "worktree", "prune", check=False)
        await git.run(epic.repo_path, "branch", "-D", epic.branch, check=False)

    async def write_plan_doc(self, ws: Workspace, task_id: str, markdown: str, *, commit: bool) -> str:
        """Save the plan in the project (D57). Committed in a split plan; left as a change otherwise."""
        rel = f"{PLAN_DOC_DIR}/{task_id}.md"
        path = ws.path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(markdown, encoding="utf-8", newline="\n")
        if commit:
            await git.run(ws.path, "add", "--", rel)
            if not await git.ok(ws.path, "diff", "--cached", "--quiet", "--", rel):
                await self._commit(ws.path, "commit", "-q", "-m", f"docs: plano {task_id}", "--", rel)
        return rel

    async def _commit(self, path: Path, *args: str) -> None:
        res = await self._git_as_user(path, *args)
        if res.returncode != 0:
            raise WorkspaceError(f"commit falhou: {(res.stderr or res.stdout).strip()[:300]}")

    async def _git_as_user(self, path: Path, *args: str) -> git.GitResult:
        """Run as the user when git knows who they are; as dev-crew otherwise (fresh machines, CI)."""
        known = await git.ok(path, "config", "user.email")
        prefix = () if known else CREW_AUTHOR
        return await git.run(path, *prefix, *args, check=False, timeout=git.DEFAULT_TIMEOUT_S * 5)

    # ------------------------------------------------------------------ diff report

    async def diff_report(self, ws: Workspace) -> list[FinalFile]:
        """Files changed vs the base branch (committed or not, plus untracked), sorted by path."""
        base = await self._diff_base(ws)
        names = await git.run(ws.path, "diff", "--name-status", "-z", "--no-renames", base)
        numstat = await git.run(ws.path, "diff", "--numstat", "-z", "--no-renames", base)
        status = await git.run(ws.path, "status", "--porcelain=v1", "-z", "-uall", "--no-renames")
        counts = _parse_numstat(numstat.stdout)

        files: dict[str, FinalFile] = {}
        for letter, rel in _parse_name_status(names.stdout):
            change = _change_of(letter)
            added, removed = counts.get(rel, (0, 0))
            files[rel] = FinalFile(path=rel, status=change, added=added, removed=removed)
        for xy, rel in _parse_status(status.stdout):
            if rel in files:
                continue
            change = _change_of(xy)
            if xy == "??" or change == "A":  # untracked, or intent-to-add not in the diff yet
                files[rel] = FinalFile(path=rel, status="A", added=_count_untracked(ws.path / rel), removed=0)
        return sorted(files.values(), key=lambda f: f.path)

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


def _parse_name_status(raw: str) -> list[tuple[str, str]]:
    """``git diff --name-status -z``: status and path alternate as NUL-separated fields."""
    parts = [p for p in raw.split("\0") if p]
    return [(parts[i], parts[i + 1]) for i in range(0, len(parts) - 1, 2)]


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
