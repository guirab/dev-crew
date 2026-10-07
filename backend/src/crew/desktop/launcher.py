"""Brings the stack up the way ``scripts/dev-up.ps1`` does, but without a console and step by step.

Order: Docker engine (opens Docker Desktop when closed) → NATS (``infra/docker-compose.yml``) →
JetStream streams → ``crew up`` as a hidden child process → wait for the gateway → open the window.
If a gateway already answers on the configured port (e.g. ``dev-up.ps1`` is running) the launcher
attaches to it and never stops it.

``shutdown`` ("Encerrar" in the tray) undoes only what this launch did: it stops the NATS container
if the launcher started it, and quits Docker Desktop if the launcher opened it.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any
from urllib.parse import urlparse

import structlog

from ..config import CrewConfig, log_dir
from . import winproc
from .icons import Status

log = structlog.get_logger(__name__)

BACKEND_DIR = Path(__file__).resolve().parents[3]
REPO_ROOT = BACKEND_DIR.parent
COMPOSE_FILE = REPO_ROOT / "infra" / "docker-compose.yml"

DOCKER_START_TIMEOUT_S = 180.0
NATS_START_TIMEOUT_S = 30.0
GATEWAY_START_TIMEOUT_S = 90.0
POLL_S = 0.5
LOG_TAIL_LINES = 15

StatusCallback = Callable[[Status, str], None]


class LauncherError(RuntimeError):
    """Startup failed. The message is shown to the user as is (pt-BR)."""


@dataclass(frozen=True)
class LaunchOptions:
    fake_agents: bool = False
    fake_speed: float = 3.0
    open_window: bool = True


def nats_address(url: str) -> tuple[str, int]:
    parsed = urlparse(url)
    return parsed.hostname or "127.0.0.1", parsed.port or 4222


def port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def console_python() -> Path:
    """``python.exe`` next to the running interpreter (the launcher itself runs on ``pythonw.exe``)."""
    exe = Path(sys.executable)
    candidate = exe.with_name("python.exe") if exe.name.lower() == "pythonw.exe" else exe
    return candidate if candidate.is_file() else exe


def tail(path: Path, lines: int = LOG_TAIL_LINES) -> str:
    try:
        return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
    except OSError:
        return ""


class Launcher:
    def __init__(
        self,
        cfg: CrewConfig,
        opts: LaunchOptions,
        *,
        config_path: Path | None = None,
        on_status: StatusCallback | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.cfg = cfg
        self.opts = opts
        self.config_path = config_path
        self.on_status: StatusCallback = on_status or (lambda status, detail: None)
        self._sleep = sleep
        self._clock = clock
        self.proc: subprocess.Popen[bytes] | None = None
        self.attached = False
        self.ready = False
        self.opened_docker = False  # this launch opened Docker Desktop: shutdown quits it
        self.started_nats = False  # this launch started the NATS container: shutdown stops it
        self._log_file: IO[Any] | None = None

    # ------------------------------------------------------------------ paths

    @property
    def url(self) -> str:
        return f"http://{self.cfg.gateway.host}:{self.cfg.gateway.port}"

    @property
    def backend_log(self) -> Path:
        return log_dir() / "backend.log"

    # ------------------------------------------------------------------ lifecycle

    def start(self) -> None:
        """Blocking. Raises ``LauncherError`` with a message for the user."""
        if self.gateway_ready():
            self.attached = True
            log.info("app_attached", url=self.url)
        else:
            nats_up = port_open(*nats_address(self.cfg.nats.url))
            sandbox = any(r.sandbox_image for r in self.cfg.repos)
            self.on_status(Status.STARTING, "verificando o Docker…")
            self.ensure_docker(required=sandbox or not nats_up)
            if not nats_up:
                self.on_status(Status.STARTING, "subindo o NATS…")
                self.start_nats()
            self.on_status(Status.STARTING, "preparando o NATS…")
            self.init_streams()
            self.on_status(Status.STARTING, "iniciando os agentes…")
            self.start_backend()
            self.wait_ready()
        self.ready = True
        self.on_status(Status.RUNNING, "pronto" if not self.opts.fake_agents else "pronto (agentes fake)")
        if self.opts.open_window:
            self.open_window()

    def open_window(self) -> None:
        winproc.open_app_window(self.url)

    def backend_exit_code(self) -> int | None:
        """Exit code of our ``crew up`` child, ``None`` while it runs (or when attached)."""
        return None if self.proc is None else self.proc.poll()

    def stop(self) -> None:
        self.ready = False
        if self.proc is not None and self.proc.poll() is None:
            log.info("app_stopping", pid=self.proc.pid)
            winproc.kill_tree(self.proc.pid)
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if self._log_file is not None:
            self._log_file.close()
            self._log_file = None

    def shutdown(self) -> None:
        """Stop the crew and whatever infrastructure this launch brought up; leave the rest alone."""
        self.stop()
        if self.attached:
            return
        if self.started_nats or self.opened_docker:
            self._best_effort("nats_stop", ["docker", "compose", "-f", str(COMPOSE_FILE), "stop"], 60)
            self.started_nats = False
        if self.opened_docker:
            self._best_effort("docker_desktop_stop", ["docker", "desktop", "stop"], 180)
            self.opened_docker = False

    def _best_effort(self, event: str, args: list[str], timeout: float) -> None:
        """Shutdown steps never raise: the user is quitting, a leftover container is not worth a dialog."""
        try:
            done = winproc.run_hidden(args, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired) as e:
            log.warning(event, ok=False, error=str(e))
            return
        log.info(event, ok=done.returncode == 0, stderr=done.stderr.strip()[-300:])

    # ------------------------------------------------------------------ steps

    def gateway_ready(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self.url}/api/repos", timeout=2) as resp:
                return bool(resp.status == 200)
        except (urllib.error.URLError, OSError, ValueError):
            return False

    def ensure_docker(self, *, required: bool) -> None:
        if shutil.which("docker") is None:
            if required:
                raise LauncherError(
                    "Docker não encontrado. Instale o Docker Desktop (winget install Docker.DockerDesktop)."
                )
            return
        if self._docker_engine_up():
            return
        if not winproc.DOCKER_DESKTOP.is_file():
            if required:
                raise LauncherError("O Docker não está rodando e o Docker Desktop não foi encontrado.")
            return
        log.info("docker_desktop_opening")
        subprocess.Popen([str(winproc.DOCKER_DESKTOP)])
        self.opened_docker = True
        deadline = self._clock() + DOCKER_START_TIMEOUT_S
        while self._clock() < deadline:
            self._sleep(3.0)
            if self._docker_engine_up():
                return
        if required:
            raise LauncherError("O Docker Desktop não subiu em 3 minutos. Abra-o e tente de novo.")

    def _docker_engine_up(self) -> bool:
        try:
            done = winproc.run_hidden(["docker", "version", "--format", "{{.Server.Version}}"], timeout=20)
        except (OSError, subprocess.TimeoutExpired):
            return False
        return done.returncode == 0

    def start_nats(self) -> None:
        done = winproc.run_hidden(["docker", "compose", "-f", str(COMPOSE_FILE), "up", "-d"], timeout=180)
        if done.returncode != 0:
            detail = (done.stderr or done.stdout).strip().splitlines()[-3:]
            raise LauncherError("Não consegui subir o NATS no Docker:\n" + "\n".join(detail))
        self.started_nats = True
        host, port = nats_address(self.cfg.nats.url)
        deadline = self._clock() + NATS_START_TIMEOUT_S
        while not port_open(host, port):
            if self._clock() > deadline:
                raise LauncherError(f"O NATS não respondeu em {host}:{port}.")
            self._sleep(POLL_S)

    def init_streams(self) -> None:
        from ..bus import Bus

        async def run() -> None:
            bus = await Bus.connect(self.cfg.nats.url, name="crew-app")
            try:
                await bus.ensure_streams()
            finally:
                await bus.close()

        try:
            asyncio.run(run())
        except Exception as e:
            raise LauncherError(f"Não consegui preparar os streams do NATS: {e}") from e

    def backend_command(self) -> list[str]:
        cmd = [str(console_python()), "-m", "crew.cli", "up"]
        if self.config_path is not None:
            cmd += ["--config", str(self.config_path)]
        if self.opts.fake_agents:
            cmd += ["--fake-agents", "--fake-speed", str(self.opts.fake_speed)]
        return cmd

    def start_backend(self) -> None:
        self.backend_log.parent.mkdir(parents=True, exist_ok=True)
        self._log_file = self.backend_log.open("ab")
        self._log_file.write(f"\n===== crew app {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n".encode())
        self._log_file.flush()
        env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
        cmd = self.backend_command()
        log.info("backend_starting", cmd=cmd)
        self.proc = winproc.spawn_hidden(cmd, cwd=BACKEND_DIR, log=self._log_file, env=env)

    def wait_ready(self) -> None:
        deadline = self._clock() + GATEWAY_START_TIMEOUT_S
        while True:
            code = self.backend_exit_code()
            if code is not None:
                raise LauncherError(
                    f"O dev-crew encerrou ao iniciar (código {code}).\n\n{tail(self.backend_log)}"
                )
            if self.gateway_ready():
                return
            if self._clock() > deadline:
                self.stop()
                raise LauncherError(f"O dev-crew não respondeu em {self.url}. Veja {self.backend_log}.")
            self._sleep(POLL_S)
