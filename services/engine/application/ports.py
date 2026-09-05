"""Ports the Engine's use cases depend on, beyond the repos and the LLM."""

from datetime import datetime
from typing import Protocol

__all__ = ["ClockPort"]


class ClockPort(Protocol):
    def now(self) -> datetime: ...
