"""Shared fixtures. ``nats_url`` starts a throwaway nats-server with JetStream on a free port."""

from __future__ import annotations

import shutil
import socket
import subprocess
import time
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest

from crew.bus import Bus

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = REPO_ROOT / "contracts" / "fixtures"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_port(port: int, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.05)
    raise RuntimeError(f"nats-server did not open port {port}")


@pytest.fixture(scope="session")
def nats_url(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    binary = shutil.which("nats-server")
    if not binary:
        pytest.skip("nats-server not found in PATH (winget install NATSAuthors.NATSServer)")
    port = _free_port()
    store = tmp_path_factory.mktemp("js")
    proc = subprocess.Popen(
        [binary, "-js", "-a", "127.0.0.1", "-p", str(port), "-sd", str(store)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_port(port)
        yield f"nats://127.0.0.1:{port}"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture
async def bus(nats_url: str) -> AsyncIterator[Bus]:
    """Connected bus with fresh streams (purged between tests)."""
    b = await Bus.connect(nats_url, name="test")
    await b.ensure_streams()
    for stream in ("CREW_JOBS", "CREW_EVENTS"):
        await b.js.purge_stream(stream)
    try:
        yield b
    finally:
        await b.close()
