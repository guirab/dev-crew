"""Entry point of ``crew app`` (runs on ``pythonw.exe``: no console, so errors go to dialogs and logs)."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import structlog

from ..config import ConfigError, load_config, log_dir
from ..logging import configure_logging
from . import winproc
from .launcher import Launcher, LaunchOptions

log = structlog.get_logger(__name__)

MUTEX_NAME = "dev-crew-app"
SECOND_INSTANCE_WAIT_S = 240.0


def _ensure_std_streams() -> None:
    """``pythonw.exe`` has no stdout/stderr: anything printing to them would crash the launcher."""
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))


def run(config_path: Path | None, opts: LaunchOptions) -> int:
    _ensure_std_streams()
    configure_logging("INFO", log_file=log_dir() / "app.log")
    try:
        cfg = load_config(config_path)
    except ConfigError as e:
        winproc.message_box(f"Configuração inválida:\n\n{e}")
        return 1

    launcher = Launcher(cfg, opts, config_path=config_path)
    if not winproc.acquire_single_instance(MUTEX_NAME):
        return _second_instance(launcher)

    from .tray import Tray

    log.info("app_started", fake_agents=opts.fake_agents, url=launcher.url)
    Tray(launcher).run()
    log.info("app_exited")
    return 0


def _second_instance(launcher: Launcher) -> int:
    """The app is already open (maybe still starting): just bring up a window once it is ready."""
    deadline = time.monotonic() + SECOND_INSTANCE_WAIT_S
    while time.monotonic() < deadline:
        if launcher.gateway_ready():
            if launcher.opts.open_window:
                launcher.open_window()
            return 0
        time.sleep(1.0)
    winproc.message_box("O Dev Crew já está aberto, mas ainda não respondeu. Veja o ícone perto do relógio.")
    return 1
