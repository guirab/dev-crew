"""Start Menu (and optional Desktop) shortcut for ``crew app``, via the ``WScript.Shell`` COM object."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from ..config import crew_home
from . import winproc
from .icons import write_ico
from .launcher import BACKEND_DIR

SHORTCUT_NAME = "Dev Crew.lnk"
DESCRIPTION = "Equipe de desenvolvimento multi-agente local"

# Values travel as environment variables, so no path ever needs PowerShell quoting.
_PS_CREATE = (
    "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:CREW_LNK);"
    "$s.TargetPath = $env:CREW_TARGET;"
    "$s.Arguments = $env:CREW_ARGS;"
    "$s.WorkingDirectory = $env:CREW_WORKDIR;"
    "$s.IconLocation = $env:CREW_ICON;"
    "$s.Description = $env:CREW_DESC;"
    "$s.Save()"
)
_PS_DESKTOP = "[Environment]::GetFolderPath('Desktop')"


class ShortcutError(RuntimeError):
    pass


@dataclass(frozen=True)
class Shortcut:
    path: Path
    target: Path
    arguments: str
    workdir: Path
    icon: Path


def gui_python() -> Path:
    """``pythonw.exe`` of the venv: PSF-signed (passes Smart App Control) and opens no console."""
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    if not pythonw.is_file():
        raise ShortcutError(f"pythonw.exe não encontrado ao lado de {exe}")
    return pythonw


def start_menu_dir() -> Path:
    return Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs"


def desktop_dir() -> Path:
    done = winproc.run_hidden(["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS_DESKTOP])
    path = done.stdout.strip()
    if done.returncode != 0 or not path:
        raise ShortcutError("não consegui descobrir a pasta da Área de Trabalho")
    return Path(path)


def app_arguments(*, fake_agents: bool = False, config_path: Path | None = None) -> str:
    args = ["-m", "crew.cli", "app"]
    if fake_agents:
        args.append("--fake-agents")
    if config_path is not None:
        args += ["--config", f'"{config_path}"']
    return " ".join(args)


def build(folder: Path, *, fake_agents: bool = False, config_path: Path | None = None) -> Shortcut:
    return Shortcut(
        path=folder / SHORTCUT_NAME,
        target=gui_python(),
        arguments=app_arguments(fake_agents=fake_agents, config_path=config_path),
        workdir=BACKEND_DIR,
        icon=crew_home() / "dev-crew.ico",
    )


def create(shortcut: Shortcut) -> Path:
    write_ico(shortcut.icon)
    shortcut.path.parent.mkdir(parents=True, exist_ok=True)
    env = {
        **os.environ,
        "CREW_LNK": str(shortcut.path),
        "CREW_TARGET": str(shortcut.target),
        "CREW_ARGS": shortcut.arguments,
        "CREW_WORKDIR": str(shortcut.workdir),
        "CREW_ICON": f"{shortcut.icon},0",
        "CREW_DESC": DESCRIPTION,
    }
    done = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS_CREATE],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )
    if done.returncode != 0 or not shortcut.path.is_file():
        raise ShortcutError(f"falha ao criar {shortcut.path}: {done.stderr.strip()}")
    return shortcut.path
