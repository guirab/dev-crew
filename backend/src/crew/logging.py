"""structlog setup: pretty console in dev, JSON lines to a file when ``log_file`` is given."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import structlog
from structlog.typing import Processor


def configure_logging(
    level: str = "INFO", *, log_file: Path | None = None, json_console: bool = False
) -> None:
    """Idempotent. ``task_id``/``job_id`` are bound by callers (``log.bind``)."""
    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
    ]
    console: Processor = (
        structlog.processors.JSONRenderer()
        if json_console
        else structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())
    )

    handlers: list[logging.Handler] = []
    stderr = logging.StreamHandler(sys.stderr)
    stderr.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared,
            processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, console],
        )
    )
    handlers.append(stderr)

    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(
            structlog.stdlib.ProcessorFormatter(
                foreign_pre_chain=shared,
                processors=[
                    structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                    structlog.processors.format_exc_info,
                    structlog.processors.JSONRenderer(),
                ],
            )
        )
        handlers.append(fh)

    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    for h in handlers:
        root.addHandler(h)
    root.setLevel(level.upper())
    for noisy in ("nats", "httpx", "httpcore", "mcp"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )
