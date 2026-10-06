"""Desktop app (``crew app``): icons, launcher sequencing and the Start Menu shortcut, without a GUI."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from crew.config import CrewConfig, GatewayCfg, RepoCfg
from crew.desktop import icons, launcher, shortcut, winproc
from crew.desktop.icons import Status
from crew.desktop.launcher import Launcher, LauncherError, LaunchOptions
from crew.desktop.tray import TOOLTIP_MAX, tooltip


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class FakeProc:
    def __init__(self, code: int | None = None, pid: int = 4242) -> None:
        self.code = code
        self.pid = pid

    def poll(self) -> int | None:
        return self.code

    def wait(self, timeout: float | None = None) -> int:
        return self.code or 0

    def kill(self) -> None:
        self.code = -9


def make_launcher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cfg: CrewConfig | None = None, **opts: Any
) -> tuple[Launcher, FakeClock, list[tuple[Status, str]]]:
    monkeypatch.setenv("CREW_HOME", str(tmp_path / "home"))
    clock = FakeClock()
    statuses: list[tuple[Status, str]] = []
    lau = Launcher(
        cfg or CrewConfig(),
        LaunchOptions(**opts),
        on_status=lambda status, detail: statuses.append((status, detail)),
        sleep=clock.sleep,
        clock=clock,
    )
    return lau, clock, statuses


# ---------------------------------------------------------------------------------------- icons


@pytest.mark.parametrize("status", list(Status))
def test_icon_has_the_status_color_in_the_center(status: Status) -> None:
    img = icons.draw_icon(64, status)
    assert img.size == (64, 64) and img.mode == "RGBA"
    r, g, b, a = img.getpixel((32, 32))  # type: ignore[misc]
    expected = Image.new("RGB", (1, 1), icons.DOT[status]).getpixel((0, 0))
    assert (r, g, b) == expected and a == 255
    assert img.getpixel((0, 0))[3] < 255  # type: ignore[index]  # rounded corner is transparent


def test_ico_and_pngs_are_written(tmp_path: Path) -> None:
    ico = icons.write_ico(tmp_path / "sub" / "app.ico")
    with Image.open(ico) as im:
        assert (256, 256) in im.info["sizes"] and (16, 16) in im.info["sizes"]
    pngs = icons.write_pngs(tmp_path / "public")
    assert [p.name for p in pngs] == ["icon-192.png", "icon-512.png"]
    with Image.open(pngs[1]) as im:
        assert im.size == (512, 512)


# ------------------------------------------------------------------------------------- launcher


def test_nats_address_defaults() -> None:
    assert launcher.nats_address("nats://10.0.0.5:4333") == ("10.0.0.5", 4333)
    assert launcher.nats_address("nats://localhost") == ("localhost", 4222)


def test_console_python_swaps_pythonw(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    (tmp_path / "python.exe").write_text("")
    monkeypatch.setattr(sys, "executable", str(tmp_path / "pythonw.exe"))
    assert launcher.console_python() == tmp_path / "python.exe"


def test_backend_command_flags(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real, _, _ = make_launcher(tmp_path, monkeypatch)
    assert real.backend_command()[1:] == ["-m", "crew.cli", "up"]
    fake, _, _ = make_launcher(tmp_path, monkeypatch, fake_agents=True, fake_speed=2.0)
    fake.config_path = tmp_path / "crew.toml"
    assert fake.backend_command()[3:] == [
        "up", "--config", str(tmp_path / "crew.toml"), "--fake-agents", "--fake-speed", "2.0",
    ]  # fmt: skip


def test_url_follows_gateway_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lau, _, _ = make_launcher(tmp_path, monkeypatch, CrewConfig(gateway=GatewayCfg(port=9999)))
    assert lau.url == "http://127.0.0.1:9999"


def test_start_attaches_to_a_running_gateway(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lau, _, statuses = make_launcher(tmp_path, monkeypatch)
    opened: list[str] = []
    monkeypatch.setattr(lau, "gateway_ready", lambda: True)
    monkeypatch.setattr(winproc, "open_app_window", opened.append)
    monkeypatch.setattr(lau, "start_backend", lambda: pytest.fail("must not start a second crew"))
    lau.start()
    assert lau.attached and lau.ready and opened == [lau.url]
    assert statuses == [(Status.RUNNING, "pronto")]
    lau.stop()  # attached: nothing of ours to kill


def test_start_runs_every_step_in_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = CrewConfig(repos=[RepoCfg(name="r", path=tmp_path, test_cmd="x", sandbox_image="node:22")])
    lau, _, statuses = make_launcher(tmp_path, monkeypatch, cfg, open_window=False)
    calls: list[str] = []
    monkeypatch.setattr(lau, "gateway_ready", lambda: False)
    monkeypatch.setattr(launcher, "port_open", lambda host, port, timeout=1.0: False)
    monkeypatch.setattr(lau, "ensure_docker", lambda *, required: calls.append(f"docker:{required}"))
    monkeypatch.setattr(lau, "start_nats", lambda: calls.append("nats"))
    monkeypatch.setattr(lau, "init_streams", lambda: calls.append("streams"))
    monkeypatch.setattr(lau, "start_backend", lambda: calls.append("backend"))
    monkeypatch.setattr(lau, "wait_ready", lambda: calls.append("wait"))
    monkeypatch.setattr(winproc, "open_app_window", lambda url: pytest.fail("open_window=False"))
    lau.start()
    assert calls == ["docker:True", "nats", "streams", "backend", "wait"]
    assert statuses[-1] == (Status.RUNNING, "pronto") and all(s is Status.STARTING for s, _ in statuses[:-1])


def test_start_skips_nats_when_it_is_already_up(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lau, _, _ = make_launcher(tmp_path, monkeypatch, fake_agents=True, open_window=False)
    calls: list[str] = []
    monkeypatch.setattr(lau, "gateway_ready", lambda: False)
    monkeypatch.setattr(launcher, "port_open", lambda host, port, timeout=1.0: True)
    monkeypatch.setattr(lau, "ensure_docker", lambda *, required: calls.append(f"docker:{required}"))
    monkeypatch.setattr(lau, "start_nats", lambda: calls.append("nats"))
    for step in ("init_streams", "start_backend", "wait_ready"):
        monkeypatch.setattr(lau, step, lambda step=step: calls.append(step))
    lau.start()
    assert calls == ["docker:False", "init_streams", "start_backend", "wait_ready"]


def test_wait_ready_reports_a_crashed_backend_with_the_log_tail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lau, _, _ = make_launcher(tmp_path, monkeypatch)
    lau.backend_log.parent.mkdir(parents=True)
    lau.backend_log.write_text("linha 1\ncrew.toml inválido: repos.0.path\n", encoding="utf-8")
    lau.proc = FakeProc(code=1)  # type: ignore[assignment]
    monkeypatch.setattr(lau, "gateway_ready", lambda: False)
    with pytest.raises(LauncherError, match=r"código 1\)[\s\S]*crew.toml inválido"):
        lau.wait_ready()


def test_wait_ready_times_out_and_stops_the_backend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lau, clock, _ = make_launcher(tmp_path, monkeypatch)
    lau.proc = FakeProc(code=None)  # type: ignore[assignment]
    killed: list[int] = []
    monkeypatch.setattr(winproc, "kill_tree", killed.append)
    monkeypatch.setattr(lau, "gateway_ready", lambda: False)
    with pytest.raises(LauncherError, match="não respondeu"):
        lau.wait_ready()
    assert clock.now > launcher.GATEWAY_START_TIMEOUT_S and killed == [4242] and not lau.ready


def test_wait_ready_returns_once_the_gateway_answers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lau, clock, _ = make_launcher(tmp_path, monkeypatch)
    lau.proc = FakeProc(code=None)  # type: ignore[assignment]
    answers = iter([False, False, True])
    monkeypatch.setattr(lau, "gateway_ready", lambda: next(answers))
    lau.wait_ready()
    assert clock.now == pytest.approx(2 * launcher.POLL_S)


def test_ensure_docker_without_docker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lau, _, _ = make_launcher(tmp_path, monkeypatch)
    monkeypatch.setattr(launcher.shutil, "which", lambda name: None)
    lau.ensure_docker(required=False)
    with pytest.raises(LauncherError, match=r"winget install Docker\.DockerDesktop"):
        lau.ensure_docker(required=True)


def test_ensure_docker_opens_docker_desktop_and_waits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lau, clock, _ = make_launcher(tmp_path, monkeypatch)
    desktop = tmp_path / "Docker Desktop.exe"
    desktop.write_text("")
    started: list[list[str]] = []
    engine = iter([False, False, True])
    monkeypatch.setattr(launcher.shutil, "which", lambda name: "docker")
    monkeypatch.setattr(winproc, "DOCKER_DESKTOP", desktop)
    monkeypatch.setattr(lau, "_docker_engine_up", lambda: next(engine))
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda args, **kw: started.append(args))
    lau.ensure_docker(required=True)
    assert started == [[str(desktop)]] and clock.now == 6.0
    assert lau.opened_docker


def test_ensure_docker_leaves_a_running_engine_alone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lau, _, _ = make_launcher(tmp_path, monkeypatch)
    monkeypatch.setattr(launcher.shutil, "which", lambda name: "docker")
    monkeypatch.setattr(lau, "_docker_engine_up", lambda: True)
    lau.ensure_docker(required=True)
    assert not lau.opened_docker


def test_start_nats_marks_it_as_ours(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lau, _, _ = make_launcher(tmp_path, monkeypatch)
    ok = subprocess.CompletedProcess(["docker"], 0, "", "")
    monkeypatch.setattr(winproc, "run_hidden", lambda args, **kw: ok)
    monkeypatch.setattr(launcher, "port_open", lambda host, port, timeout=1.0: True)
    lau.start_nats()
    assert lau.started_nats


def test_start_nats_surfaces_compose_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lau, _, _ = make_launcher(tmp_path, monkeypatch)
    failed = subprocess.CompletedProcess(["docker"], 1, "", "a\nb\nerror during connect: pipe not found\n")
    monkeypatch.setattr(winproc, "run_hidden", lambda args, **kw: failed)
    with pytest.raises(LauncherError, match="pipe not found"):
        lau.start_nats()


def test_stop_kills_the_whole_tree_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lau, _, _ = make_launcher(tmp_path, monkeypatch)
    proc = FakeProc(code=None, pid=77)
    lau.proc = proc  # type: ignore[assignment]
    lau.ready = True
    killed: list[int] = []

    def kill(pid: int) -> None:
        killed.append(pid)
        proc.code = 1

    monkeypatch.setattr(winproc, "kill_tree", kill)
    lau.stop()
    lau.stop()
    assert killed == [77] and not lau.ready and lau.backend_exit_code() == 1


@pytest.mark.parametrize(
    ("opened_docker", "started_nats", "expected"),
    [
        (True, True, ["compose stop", "desktop stop"]),
        (True, False, ["compose stop", "desktop stop"]),  # NATS came back with Docker: ours too
        (False, True, ["compose stop"]),  # Docker was already open: it stays
        (False, False, []),  # nothing was ours
    ],
)
def test_shutdown_undoes_only_what_this_launch_did(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    opened_docker: bool,
    started_nats: bool,
    expected: list[str],
) -> None:
    lau, _, _ = make_launcher(tmp_path, monkeypatch)
    lau.proc = FakeProc(code=0)  # type: ignore[assignment]
    lau.opened_docker, lau.started_nats = opened_docker, started_nats
    ran: list[str] = []

    def run_hidden(args: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        ran.append(" ".join(args[1:2] + args[-1:]))
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(winproc, "run_hidden", run_hidden)
    lau.shutdown()
    lau.shutdown()  # idempotent: a second "Encerrar" does nothing more
    assert ran == expected


def test_shutdown_never_touches_an_attached_crew(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lau, _, _ = make_launcher(tmp_path, monkeypatch)
    lau.attached, lau.opened_docker, lau.started_nats = True, True, True
    monkeypatch.setattr(winproc, "run_hidden", lambda args, **kw: pytest.fail("attached: hands off"))
    lau.shutdown()


def test_shutdown_survives_docker_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lau, _, _ = make_launcher(tmp_path, monkeypatch)
    lau.opened_docker = True

    def boom(args: list[str], **kw: Any) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(args, 1)

    monkeypatch.setattr(winproc, "run_hidden", boom)
    lau.shutdown()
    assert not lau.opened_docker


# ----------------------------------------------------------------------------------- tray / shortcut


def test_tooltip_fits_the_windows_limit() -> None:
    assert tooltip("pronto") == "Dev Crew · pronto"
    assert len(tooltip("x" * 500)) == TOOLTIP_MAX


def test_shortcut_points_at_pythonw_in_the_backend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CREW_HOME", str(tmp_path / "home"))
    (tmp_path / "pythonw.exe").write_text("")
    monkeypatch.setattr(sys, "executable", str(tmp_path / "python.exe"))
    sc = shortcut.build(tmp_path / "menu", fake_agents=True, config_path=Path("C:/cfg dir/crew.toml"))
    assert sc.path == tmp_path / "menu" / "Dev Crew.lnk"
    assert sc.target == tmp_path / "pythonw.exe"
    assert sc.workdir == launcher.BACKEND_DIR and (sc.workdir / "pyproject.toml").is_file()
    assert sc.arguments == f'-m crew.cli app --fake-agents --config "{Path("C:/cfg dir/crew.toml")}"'
    assert sc.icon == tmp_path / "home" / "dev-crew.ico"


def test_shortcut_needs_pythonw(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "executable", str(tmp_path / "python.exe"))
    with pytest.raises(shortcut.ShortcutError, match=r"pythonw\.exe"):
        shortcut.gui_python()
