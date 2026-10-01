"""`crew agent ...` sub-commands. Owned by Stream B (backend-agents)."""

import typer

app = typer.Typer(help="Agentes (Stream B)", no_args_is_help=True)


@app.command("list")
def list_agents() -> None:
    """Lista os agentes conhecidos."""
    from ..contracts import AGENTS

    for name in AGENTS:
        typer.echo(name)
