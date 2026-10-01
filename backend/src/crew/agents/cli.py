"""`crew agent ...` sub-commands. Owned by Stream B (backend-agents)."""

from __future__ import annotations

import asyncio
import sys
import tempfile
import time
from pathlib import Path
from typing import Annotated

import typer

from ..bus import FatalJobError, RetryableJobError
from ..contracts import AGENTS, AgentJob, AgentResultEvt
from .progress import ProgressLine
from .sample import REPO_ROOT, SAMPLE_REPO, init_sample_repo
from .settings import DEFAULT_MODELS, AgentRuntimeSettings

app = typer.Typer(help="Agentes (Stream B)", no_args_is_help=True)


@app.command("list")
def list_agents() -> None:
    """Lista os agentes conhecidos."""
    for name in AGENTS:
        typer.echo(name)


def _resolve_workspace(job: AgentJob, override: Path | None) -> Path | None:
    raw = override or (Path(job.workspace_path) if job.workspace_path else None)
    if raw is None:
        return None
    path = raw if raw.is_absolute() else REPO_ROOT / raw
    return path.resolve()


@app.command("try")
def try_agent(
    agent: Annotated[str, typer.Argument(help=f"Um de: {', '.join(AGENTS)}")],
    job_file: Annotated[Path, typer.Option("--job", help="JSON de um AgentJob (ver fixtures/jobs)")],
    fake: Annotated[bool, typer.Option("--fake", help="Agente roteirizado, zero tokens")] = False,
    workspace: Annotated[Path | None, typer.Option(help="Sobrescreve workspace_path do job")] = None,
    model: Annotated[str | None, typer.Option(help="Modelo (padrão por agente)")] = None,
    speed: Annotated[float, typer.Option(help="Velocidade do modo fake (1000 = instantâneo)")] = 4.0,
    escalate: Annotated[bool, typer.Option("--escalate", help="Modo fake: Tester sempre falha")] = False,
) -> None:
    """Roda um agente sem NATS: progresso no stderr, resultado (JSON) no stdout."""
    from .service import make_runner

    for stream in (sys.stdout, sys.stderr):  # Windows pipes default to a legacy code page
        stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

    if agent not in AGENTS:
        raise typer.BadParameter(f"agente desconhecido: {agent}", param_hint="AGENT")
    try:
        job = AgentJob.model_validate_json(job_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        typer.echo(f"job inválido ({job_file}): {e}", err=True)
        raise typer.Exit(2) from e
    if job.agent != agent:
        typer.echo(f"o job é do agente '{job.agent}', não '{agent}'", err=True)
        raise typer.Exit(2)

    ws = _resolve_workspace(job, workspace)
    if ws is not None and ws == SAMPLE_REPO.resolve():
        # never run an agent on the committed fixture: work on a fresh git copy
        ws = init_sample_repo(Path(tempfile.mkdtemp(prefix="crew-try-")) / "repo")
        typer.echo(f"[workspace] cópia temporária do sample-repo: {ws}", err=True)
    job = job.model_copy(update={"workspace_path": str(ws) if ws else None})

    agent_name = job.agent
    settings = AgentRuntimeSettings(
        model=model or DEFAULT_MODELS[agent_name],
        fake=fake,
        fake_speed=speed,
        fake_escalate=escalate,
    )

    async def emit(line: ProgressLine) -> None:
        typer.echo(f"[{line.kind}] {line.text}", err=True)

    async def go() -> AgentResultEvt:
        started = time.monotonic()
        outcome = await make_runner(settings).run(job, emit)
        return AgentResultEvt(
            agent=agent_name,
            job_id=job.job_id,
            output=outcome.output,
            cost_usd=outcome.cost_usd,
            session_id=outcome.session_id,
            duration_s=round(time.monotonic() - started, 3),
        )

    try:
        result = asyncio.run(go())
    except (FatalJobError, RetryableJobError) as e:
        kind = "transitório" if isinstance(e, RetryableJobError) else "fatal"
        typer.echo(f"[falhou:{kind}] {e}", err=True)
        raise typer.Exit(1) from e
    typer.echo(result.model_dump_json(indent=2))
