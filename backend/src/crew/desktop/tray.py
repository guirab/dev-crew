"""Tray icon: shows the launcher status and is the only way to stop the crew started by the app."""

from __future__ import annotations

import threading

import pystray
import structlog

from ..config import log_dir
from . import winproc
from .icons import Status, draw_icon
from .launcher import Launcher, LauncherError

log = structlog.get_logger(__name__)

ICON_PX = 64
MONITOR_EVERY_S = 2.0
TOOLTIP_MAX = 120  # Windows truncates tray tooltips at 127 characters


def tooltip(detail: str) -> str:
    return f"Dev Crew · {detail}"[:TOOLTIP_MAX]


class Tray:
    def __init__(self, launcher: Launcher) -> None:
        self.launcher = launcher
        self._stopping = threading.Event()
        self._busy = threading.Lock()  # held while the stack is being started or stopped from the menu
        launcher.on_status = self.set_status
        self.icon = pystray.Icon(
            "dev-crew",
            draw_icon(ICON_PX, Status.STARTING),
            tooltip("iniciando…"),
            menu=pystray.Menu(
                pystray.MenuItem("Abrir Dev Crew", self._open, default=True, enabled=self._can_open),
                pystray.MenuItem(
                    "Parar o Docker (economizar memória)", self._suspend, enabled=self._can_suspend
                ),
                pystray.MenuItem("Ver logs", self._open_logs),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Encerrar", self._quit),
            ),
        )

    def run(self) -> None:
        """Blocks the main thread until "Encerrar". The startup runs in pystray's setup thread."""
        self.icon.run(setup=self._setup)

    def set_status(self, status: Status, detail: str) -> None:
        self.icon.icon = draw_icon(ICON_PX, status)
        self.icon.title = tooltip(detail)

    # ------------------------------------------------------------------ threads

    def _setup(self, icon: pystray.Icon) -> None:
        icon.visible = True
        try:
            self.launcher.start()
        except LauncherError as e:
            log.error("app_start_failed", error=str(e))
            self.set_status(Status.ERROR, "falhou ao iniciar")
            winproc.message_box(str(e))
            return
        except Exception as e:
            log.exception("app_start_crashed")
            self.set_status(Status.ERROR, "falhou ao iniciar")
            winproc.message_box(f"Erro inesperado ao iniciar: {e}\n\nVeja os logs em {log_dir()}.")
            return
        if not self.launcher.attached:
            self._monitor()

    def _monitor(self) -> None:
        """Flags a crew that died by itself; a stop or start the user asked for is not an error."""
        reported = False
        while not self._stopping.wait(MONITOR_EVERY_S):
            if self.launcher.suspended or self._busy.locked():
                reported = False
                continue
            code = self.launcher.backend_exit_code()
            if code is None or reported:
                continue
            reported = True
            log.error("backend_exited", code=code)
            self.launcher.ready = False
            self.set_status(Status.ERROR, f"parou (código {code})")
            self.icon.notify("O dev-crew parou. Veja os logs e abra o app de novo.", "Dev Crew")

    # ------------------------------------------------------------------ menu

    def _can_open(self, _item: pystray.MenuItem) -> bool:
        return not self._busy.locked() and (self.launcher.ready or self.launcher.suspended)

    def _can_suspend(self, _item: pystray.MenuItem) -> bool:
        return not self._busy.locked() and self.launcher.can_suspend()

    def _open(self, _icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        """Opens the window; when the Docker was stopped from the menu, brings everything back up first."""
        if not self._busy.acquire(blocking=False):
            return
        try:
            if self.launcher.suspended:
                self.set_status(Status.STARTING, "iniciando…")
                self.launcher.start()  # also opens the window
            elif self.launcher.ready:
                self.launcher.open_window()
        except LauncherError as e:
            log.error("app_resume_failed", error=str(e))
            self.set_status(Status.ERROR, "falhou ao iniciar")
            winproc.message_box(str(e))
        except Exception as e:
            log.exception("app_resume_crashed")
            self.set_status(Status.ERROR, "falhou ao iniciar")
            winproc.message_box(f"Erro inesperado ao iniciar: {e}\n\nVeja os logs em {log_dir()}.")
        finally:
            self._busy.release()

    def _suspend(self, icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        if not self._busy.acquire(blocking=False):
            return
        try:
            self.set_status(Status.STARTING, "parando o Docker…")
            try:
                note = self.launcher.suspend()
            except LauncherError as e:
                log.warning("app_suspend_refused", error=str(e))
                self.set_status(Status.RUNNING, "pronto")
                icon.notify(str(e), "Dev Crew")
                return
            self.set_status(Status.STOPPED, f"parado · {note} · abra para retomar")
            icon.notify(f"{note}. Clique em Abrir Dev Crew para retomar.", "Dev Crew")
        finally:
            self._busy.release()

    def _open_logs(self, _icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        log_dir().mkdir(parents=True, exist_ok=True)
        winproc.open_path(log_dir())

    def _quit(self, icon: pystray.Icon, _item: pystray.MenuItem) -> None:
        self._stopping.set()
        detail = "encerrando e fechando o Docker…" if self.launcher.opened_docker else "encerrando…"
        self.set_status(Status.STARTING, detail)
        self.launcher.shutdown()
        icon.stop()
