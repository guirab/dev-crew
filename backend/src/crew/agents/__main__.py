"""``python -m crew.agents <name>``: run one agent worker as a standalone process.

Environment: ``CREW_NATS_URL`` (default ``nats://127.0.0.1:4222``), ``CREW_MODEL_<AGENT>``,
``CREW_FAKE_AGENTS``, ``CREW_FAKE_SPEED``, ``CREW_FAKE_ESCALATE``, ``CREW_MAX_TURNS``.
"""

from __future__ import annotations

import asyncio
import signal
import sys
from typing import get_args

from ..bus import Bus
from ..contracts import AgentName
from .service import run_agent
from .settings import nats_url_from_env, settings_from_env


async def serve(agent: AgentName) -> None:
    settings = settings_from_env(agent)
    bus = await Bus.connect(nats_url_from_env(), name=f"crew-agent-{agent}")
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()

    def request_stop(*_: object) -> None:
        loop.call_soon_threadsafe(stop.set)

    # add_signal_handler is not available on Windows event loops
    signal.signal(signal.SIGINT, request_stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, request_stop)
    try:
        await bus.ensure_streams()
        await run_agent(bus, agent, settings=settings, stop=stop)
    finally:
        await bus.close()


def main(argv: list[str]) -> int:
    names = get_args(AgentName)
    if len(argv) != 1 or argv[0] not in names:
        print(f"usage: python -m crew.agents <{'|'.join(names)}>", file=sys.stderr)
        return 2
    agent: AgentName = next(n for n in names if n == argv[0])
    asyncio.run(serve(agent))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
