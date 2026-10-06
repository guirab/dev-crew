"""`crew` command line: up, svc, doctor, cleanup, app, install-app, streams, gen-schema.

`agent` is Stream B's.
"""

from __future__ import annotations

import asyncio
import os
import signal
from pathlib import Path

import typer

from .agents.cli import app as agent_app

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_NATS_URL = os.environ.get("CREW_NATS_URL", "nats://127.0.0.1:4222")

app = typer.Typer(help="dev-crew: equipe de dev multi-agente local", no_args_is_help=True)
streams_app = typer.Typer(help="Streams e consumers do NATS JetStream", no_args_is_help=True)
app.add_typer(streams_app, name="streams")
app.add_typer(agent_app, name="agent")

ConfigOpt = typer.Option(
    None, "--config", "-c", help="Caminho do crew.toml (padrão: CREW_CONFIG, ./, ~/.dev-crew)"
)
LogLevelOpt = typer.Option("INFO", "--log-level", help="DEBUG, INFO, WARNING...")


@app.command("gen-schema")
def gen_schema(
    out: Path = typer.Option(REPO_ROOT / "contracts" / "schema.json", help="Arquivo de saída"),
) -> None:
    """Exporta o JSON Schema dos contratos (fonte dos tipos TS do front)."""
    from .schema import dump_schema

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(dump_schema(), encoding="utf-8")
    typer.echo(f"schema -> {out}")


@streams_app.command("init")
def streams_init(url: str = typer.Option(DEFAULT_NATS_URL, help="URL do NATS")) -> None:
    """Cria/atualiza streams CREW_JOBS e CREW_EVENTS e os consumers duráveis. Idempotente."""
    from .bus import Bus

    async def _run() -> None:
        bus = await Bus.connect(url, name="crew-cli")
        try:
            await bus.ensure_streams()
        finally:
            await bus.close()

    asyncio.run(_run())
    typer.echo("streams ok")


# ----------------------------------------------------------------------------------------- up / svc


def _run_stack(
    config: Path | None,
    *,
    only: str | None,
    fake_agents: bool,
    fake_speed: float,
    fake_escalate: bool,
    builtin_fakes: bool,
    port: int | None,
    no_frontend: bool,
    log_level: str,
) -> None:
    from .config import ConfigError, load_config, load_secrets, log_dir
    from .logging import configure_logging
    from .stack import StackError, StackOptions, run_stack

    configure_logging(log_level, log_file=log_dir() / "crew.log")
    try:
        cfg = load_config(config)
        if port is not None:
            cfg = cfg.model_copy(update={"gateway": cfg.gateway.model_copy(update={"port": port})})
        opts = StackOptions(
            fake_agents=fake_agents,
            fake_speed=fake_speed,
            fake_escalate=fake_escalate,
            builtin_fakes=builtin_fakes,
            **({"dist": None} if no_frontend else {}),
        )

        async def main() -> None:
            stop = asyncio.Event()
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                try:
                    loop.add_signal_handler(sig, stop.set)
                except NotImplementedError:  # Windows: asyncio.run turns Ctrl+C into a cancellation
                    break
            typer.echo(f"crew {only or 'up'}: http://{cfg.gateway.host}:{cfg.gateway.port}  (Ctrl+C encerra)")
            await run_stack(cfg, load_secrets(), opts, stop, only=only)

        asyncio.run(main())
    except (ConfigError, StackError) as e:
        typer.secho(str(e), fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from e
    except KeyboardInterrupt:
        typer.echo("encerrado")


@app.command("up")
def up(
    config: Path | None = ConfigOpt,
    fake_agents: bool = typer.Option(
        False, "--fake-agents", envvar="CREW_FAKE_AGENTS", help="Agentes roteirizados, zero tokens"
    ),
    fake_speed: float = typer.Option(
        1.0, "--fake-speed", min=0.01, help="Multiplicador de velocidade dos fakes"
    ),
    fake_escalate: bool = typer.Option(False, "--fake-escalate", help="Fakes forçam escalada no Tester"),
    builtin_fakes: bool = typer.Option(False, "--builtin-fakes", hidden=True),
    port: int | None = typer.Option(None, "--port", help="Sobrescreve [gateway].port"),
    no_frontend: bool = typer.Option(False, "--no-frontend", help="Não serve frontend/dist"),
    log_level: str = LogLevelOpt,
) -> None:
    """Sobe tudo num processo: orquestrador, agentes e gateway."""
    _run_stack(
        config,
        only=None,
        fake_agents=fake_agents,
        fake_speed=fake_speed,
        fake_escalate=fake_escalate,
        builtin_fakes=builtin_fakes,
        port=port,
        no_frontend=no_frontend,
        log_level=log_level,
    )


@app.command("svc")
def svc(
    name: str = typer.Argument(..., help="orchestrator | gateway | agent:<nome>"),
    config: Path | None = ConfigOpt,
    fake_agents: bool = typer.Option(False, "--fake-agents", envvar="CREW_FAKE_AGENTS"),
    fake_speed: float = typer.Option(1.0, "--fake-speed", min=0.01),
    fake_escalate: bool = typer.Option(False, "--fake-escalate"),
    builtin_fakes: bool = typer.Option(False, "--builtin-fakes", hidden=True),
    port: int | None = typer.Option(None, "--port"),
    no_frontend: bool = typer.Option(False, "--no-frontend"),
    log_level: str = LogLevelOpt,
) -> None:
    """Sobe um serviço isolado (modo distribuído; mesma lógica do `up`, comunicação só via NATS)."""
    from .stack import StackError, validate_service_name

    try:
        validate_service_name(name)
    except StackError as e:
        typer.secho(str(e), fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from e
    _run_stack(
        config,
        only=name,
        fake_agents=fake_agents,
        fake_speed=fake_speed,
        fake_escalate=fake_escalate,
        builtin_fakes=builtin_fakes,
        port=port,
        no_frontend=no_frontend,
        log_level=log_level,
    )


# ------------------------------------------------------------------------------------ doctor / cleanup


@app.command("doctor")
def doctor(
    config: Path | None = ConfigOpt,
    skip_tests: bool = typer.Option(False, "--skip-tests", help="Não roda o test_cmd de cada repo"),
) -> None:
    """Checa NATS, login do Claude, git, repos e test_cmd; diz o que falta e como resolver."""
    import sys

    from . import doctor as d

    for stream in (sys.stdout, sys.stderr):  # Windows consoles default to a legacy code page
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8")
    checks = asyncio.run(d.run_checks(config, run_tests=not skip_tests))
    colors = {"ok": typer.colors.GREEN, "warn": typer.colors.YELLOW, "fail": typer.colors.RED}
    for line in d.render(checks, lambda text, status: typer.style(text, fg=colors[status], bold=True)):
        typer.echo(line)
    raise typer.Exit(d.exit_code(checks))


@app.command("cleanup")
def cleanup(
    task_id: str = typer.Argument(..., help="Ex.: T-7"),
    config: Path | None = ConfigOpt,
    force: bool = typer.Option(False, "--force", help="Remove mesmo com mudanças não commitadas"),
) -> None:
    """Remove o worktree (e a branch crew/<task>) de uma tarefa, e o container do sandbox."""
    from . import sandbox
    from .config import ConfigError, load_config
    from .workspace.manager import WorkspaceError, WorkspaceManager

    try:
        cfg = load_config(config)
        manager = WorkspaceManager(cfg.workspace.root, cfg.workspace.mode)
        found = manager.find(task_id)
        if not found:
            typer.secho(
                f"nenhum worktree de {task_id} em {cfg.workspace.root}", fg=typer.colors.RED, err=True
            )
            raise typer.Exit(1)

        async def _run() -> None:
            for path in found:
                repo = cfg.repo(path.parent.name)
                ws = manager.locate(task_id, repo)
                await manager.cleanup(ws, force=force)
                typer.echo(f"removido: {path}")
                if repo.sandbox_image and sandbox.docker_available():
                    if await sandbox.remove(task_id, repo.name, tuple(repo.deps_dirs)):
                        typer.echo(f"container removido: {sandbox.container_name(task_id, repo.name)}")

        asyncio.run(_run())
    except (ConfigError, WorkspaceError) as e:
        typer.secho(str(e), fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from e


# ------------------------------------------------------------------------------------ desktop app


@app.command("init-demo")
def init_demo(
    dest: Path | None = typer.Option(None, "--dest", help="Destino (padrão: ~/.dev-crew/repos/demo)"),
) -> None:
    """Cria um repo git de demonstração e imprime o bloco [[repos]] pra colar no crew.toml."""
    import subprocess
    import sys

    from .agents.sample import init_sample_repo
    from .config import crew_home

    target = (dest or crew_home() / "repos" / "demo").expanduser().resolve()
    try:
        init_sample_repo(target)
    except (FileExistsError, FileNotFoundError, subprocess.CalledProcessError) as e:
        typer.secho(str(e), fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from e
    # the app launches with the venv's pythonw, so a bare `python` would miss pytest: pin the venv python
    test_cmd = f'"{Path(sys.executable).as_posix()}" -m pytest -q'
    typer.echo(f"repo demo criado: {target}")
    typer.echo("Cole no seu crew.toml:\n")
    typer.echo("[[repos]]")
    typer.echo('name = "demo"')
    typer.echo(f'path = "{target.as_posix()}"')
    typer.echo('base_branch = "main"')
    typer.echo(f"test_cmd = '{test_cmd}'")
    typer.echo('test_globs = ["tests/**", "**/test_*.py"]')


@app.command("app")
def desktop_app(
    config: Path | None = ConfigOpt,
    fake_agents: bool = typer.Option(False, "--fake-agents", help="Agentes roteirizados, zero tokens"),
    fake_speed: float = typer.Option(3.0, "--fake-speed", min=0.01),
    no_window: bool = typer.Option(False, "--no-window", help="Só sobe o crew, sem abrir a janela"),
) -> None:
    """App desktop: sobe Docker, NATS e o crew escondidos, com ícone na bandeja, e abre a janela."""
    from .desktop.app import run
    from .desktop.launcher import LaunchOptions

    opts = LaunchOptions(fake_agents=fake_agents, fake_speed=fake_speed, open_window=not no_window)
    raise typer.Exit(run(config, opts))


@app.command("install-app")
def install_app(
    config: Path | None = typer.Option(None, "--config", "-c", help="crew.toml fixo no atalho"),
    desktop: bool = typer.Option(False, "--desktop", help="Também cria o atalho na Área de Trabalho"),
    fake_agents: bool = typer.Option(False, "--fake-agents", help="Atalho abre com agentes fake"),
) -> None:
    """Cria o atalho "Dev Crew" no menu Iniciar (e na Área de Trabalho com --desktop)."""
    from .desktop import shortcut

    try:
        folders = [shortcut.start_menu_dir()]
        if desktop:
            folders.append(shortcut.desktop_dir())
        resolved = config.resolve() if config is not None else None
        for folder in folders:
            path = shortcut.create(shortcut.build(folder, fake_agents=fake_agents, config_path=resolved))
            typer.echo(f"atalho criado: {path}")
    except shortcut.ShortcutError as e:
        typer.secho(str(e), fg=typer.colors.RED, err=True)
        raise typer.Exit(1) from e


if __name__ == "__main__":
    app()
