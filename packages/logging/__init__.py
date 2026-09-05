"""Structured logging shared by every service.

One JSON object per line on stdout, so a log shipper needs no parser. Every
record carries the service name; records emitted inside a job also carry its
`job_id`, which is how a single job is followed across the queue boundary
for every service.
"""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

__all__ = ["JsonFormatter", "bind_job_id", "configure_logging", "current_job_id", "get_logger"]

_SERVICE: ContextVar[str] = ContextVar("service", default="unknown")
_JOB_ID: ContextVar[str | None] = ContextVar("job_id", default=None)

# LogRecord attributes that are not caller-supplied extras.
_RESERVED = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {
    "message",
    "asctime",
    "taskName",
}


class JsonFormatter(logging.Formatter):
    """Render a record as a single JSON line, including any `extra` fields."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
            "service": _SERVICE.get(),
        }
        job_id = _JOB_ID.get()
        if job_id is not None:
            payload["job_id"] = job_id
        for key, value in record.__dict__.items():
            if key not in _RESERVED:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(service: str, *, level: int = logging.INFO) -> None:
    """Install the JSON formatter on the root logger and name the service.

    Idempotent: calling it twice replaces the handler rather than doubling output.
    """
    _SERVICE.set(service)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)


@contextmanager
def bind_job_id(job_id: str) -> Iterator[None]:
    """Attach `job_id` to every record emitted inside the block."""
    token = _JOB_ID.set(job_id)
    try:
        yield
    finally:
        _JOB_ID.reset(token)


def current_job_id() -> str | None:
    """The job id bound to the current context, if any."""
    return _JOB_ID.get()


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
