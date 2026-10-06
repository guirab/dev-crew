"""Per-task Docker sandbox (D41): agent commands run in a container that only sees the task worktree.

One container per task, named after the task, kept until ``crew cleanup``:

- the worktree is bind-mounted at ``/work`` (edits made on the host show up inside and vice versa);
- the repository's git dir is mounted **read-only** at ``/repo.git`` so ``git status/diff`` work but no
  script can commit;
- dependency dirs (``node_modules``, ``.venv``...) live in Docker volumes, outside the Windows worktree;
- the setup command runs with network, then the container is disconnected for good.

Both the orchestrator (create/setup/remove) and the agents (``exec``) derive the container name from
``task_id`` + repo, so nothing else has to travel on the bus.
"""

from __future__ import annotations

import asyncio
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import structlog

log = structlog.get_logger(__name__)

WORKDIR = "/work"
GIT_MOUNT = "/repo.git"
SETUP_MARKER = "/tmp/.crew-setup-done"
DOCKER_TIMEOUT_S = 120.0
SETUP_TIMEOUT_S = 20 * 60.0
OUTPUT_TAIL_CHARS = 4_000
_SLUG_RE = re.compile(r"[^a-z0-9]+")


class SandboxError(RuntimeError):
    """The sandbox could not be prepared or used. The message is shown to the user (pt-BR)."""


@dataclass(frozen=True)
class GitLayout:
    """Where the worktree's git data lives on the host (from ``git rev-parse``)."""

    common_dir: Path  # <repo>/.git
    git_dir: Path  # <repo>/.git/worktrees/<name> (worktree) or the common dir (inplace)
    autocrlf: str | None  # host core.autocrlf, so CRLF checkouts are not reported as modified


@dataclass(frozen=True)
class ExecResult:
    exit_code: int
    output: str  # stdout + stderr, interleaved


def _slug(text: str) -> str:
    return _SLUG_RE.sub("-", text.lower()).strip("-") or "x"


def container_name(task_id: str, repo: str) -> str:
    return f"crew-{_slug(repo)}-{_slug(task_id)}"


def volume_name(task_id: str, repo: str, deps_dir: str) -> str:
    return f"{container_name(task_id, repo)}-{_slug(deps_dir)}"


def tail(text: str, limit: int = OUTPUT_TAIL_CHARS) -> str:
    return text if len(text) <= limit else "[...]\n" + text[-limit:]


def docker_available() -> bool:
    return shutil.which("docker") is not None


async def _docker(*args: str, timeout: float = DOCKER_TIMEOUT_S) -> subprocess.CompletedProcess[str]:
    exe = shutil.which("docker")
    if exe is None:
        raise SandboxError("docker não encontrado: instale/abra o Docker Desktop")

    def run() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [exe, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )

    try:
        return await asyncio.to_thread(run)
    except subprocess.TimeoutExpired as e:
        raise SandboxError(f"docker {args[0]} passou de {timeout:.0f}s") from e


def run_args(
    task_id: str, repo: str, image: str, workspace: Path, layout: GitLayout, deps_dirs: tuple[str, ...]
) -> list[str]:
    """Arguments of ``docker run`` for the task container (pure, unit tested)."""
    name = container_name(task_id, repo)
    git_dir = GIT_MOUNT
    if layout.git_dir != layout.common_dir:
        git_dir = str(PurePosixPath(GIT_MOUNT) / layout.git_dir.relative_to(layout.common_dir).as_posix())
    git_config = [("safe.directory", "*")]
    if layout.autocrlf:
        git_config.append(("core.autocrlf", layout.autocrlf))
    args = [
        "run", "-d",
        "--name", name,
        "--label", f"crew.task={task_id}",
        "--label", f"crew.repo={repo}",
        "--mount", f"type=bind,source={workspace},target={WORKDIR}",
        "--mount", f"type=bind,source={layout.common_dir},target={GIT_MOUNT},readonly",
    ]  # fmt: skip
    for deps in deps_dirs:
        target = PurePosixPath(WORKDIR) / PurePosixPath(deps)
        args += ["--mount", f"type=volume,source={volume_name(task_id, repo, deps)},target={target}"]
    env = {"GIT_DIR": git_dir, "GIT_WORK_TREE": WORKDIR, "GIT_CONFIG_COUNT": str(len(git_config))}
    for i, (key, value) in enumerate(git_config):
        env[f"GIT_CONFIG_KEY_{i}"] = key
        env[f"GIT_CONFIG_VALUE_{i}"] = value
    for key, value in env.items():
        args += ["-e", f"{key}={value}"]
    args += ["-w", WORKDIR, "--entrypoint", "sleep", image, "infinity"]
    return args


async def _state(name: str) -> str | None:
    """``running``/``exited``/... or ``None`` when the container does not exist."""
    res = await _docker("inspect", "-f", "{{.State.Status}}", name)
    return res.stdout.strip() if res.returncode == 0 else None


async def create(
    task_id: str, repo: str, image: str, workspace: Path, layout: GitLayout, deps_dirs: tuple[str, ...]
) -> str:
    """Start (or reuse after a restart) the task container. Returns its name."""
    name = container_name(task_id, repo)
    state = await _state(name)
    if state == "running":
        log.info("sandbox_reused", container=name)
        return name
    if state is not None:
        start = await _docker("start", name)
        if start.returncode != 0:
            raise SandboxError(f"não consegui religar o container {name}: {tail(start.stderr)}")
        return name
    args = run_args(task_id, repo, image, workspace, layout, deps_dirs)
    res = await _docker(*args, timeout=SETUP_TIMEOUT_S)  # may pull the image
    if res.returncode != 0:
        raise SandboxError(f"docker run falhou ({image}): {tail(res.stderr.strip())}")
    log.info("sandbox_created", container=name, image=image)
    return name


async def setup(name: str, command: str | None) -> None:
    """Run the repo setup with network (once), then cut the network for good."""
    done = await _docker("exec", name, "test", "-f", SETUP_MARKER)
    if command and done.returncode != 0:
        await _docker("network", "connect", "bridge", name)  # no-op error when already connected
        res = await _docker(
            "exec", "-w", WORKDIR, name, "bash", "-lc", f"{command} && touch {SETUP_MARKER}",
            timeout=SETUP_TIMEOUT_S,
        )  # fmt: skip
        if res.returncode != 0:
            output = (res.stdout + res.stderr).strip()
            raise SandboxError(f"setup falhou (`{command}`, código {res.returncode}):\n{tail(output)}")
        log.info("sandbox_setup_done", container=name)
    off = await _docker("network", "disconnect", "--force", "bridge", name)
    if off.returncode != 0 and "is not connected" not in off.stderr:
        raise SandboxError(f"não consegui tirar a rede do container {name}: {tail(off.stderr)}")


async def exec_command(name: str, command: str, timeout_s: float) -> ExecResult:
    """Run one agent command inside the container (``bash -lc`` in ``/work``), killed after ``timeout_s``."""
    seconds = max(1, int(timeout_s))
    res = await _docker(
        "exec", "-w", WORKDIR, name, "timeout", "-k", "5", str(seconds), "bash", "-lc", f"{command} 2>&1",
        timeout=seconds + 30,
    )  # fmt: skip
    if "No such container" in res.stderr or "is not running" in res.stderr:
        raise SandboxError(f"container {name} não está rodando: {res.stderr.strip()}")
    output = res.stdout + res.stderr  # the command's stderr is already in stdout (2>&1)
    if res.returncode == 124:
        output += f"\n[dev-crew] comando interrompido após {seconds}s"
    return ExecResult(res.returncode, output)


async def remove(task_id: str, repo: str, deps_dirs: tuple[str, ...]) -> bool:
    """Remove the container and its dependency volumes. ``True`` if a container existed."""
    name = container_name(task_id, repo)
    existed = (await _docker("rm", "-f", name)).returncode == 0
    for deps in deps_dirs:
        await _docker("volume", "rm", "-f", volume_name(task_id, repo, deps))
    return existed
