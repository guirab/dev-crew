"""`crew` command line. M0 ships gen-schema and streams; Stream A adds up/svc/doctor/cleanup."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import typer

from .agents.cli import app as agent_app

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_NATS_URL = os.environ.get("CREW_NATS_URL", "nats://127.0.0.1:4222")

app = typer.Typer(help="dev-crew: equipe de dev multi-agente local", no_args_is_help=True)
streams_app = typer.Typer(help="Streams e consumers do NATS JetStream", no_args_is_help=True)
app.add_typer(streams_app, name="streams")
app.add_typer(agent_app, name="agent")


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


if __name__ == "__main__":
    app()
