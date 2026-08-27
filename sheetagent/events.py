"""Progress events emitted while the agent works.

The CLI subscribes and prints them live; the MCP server forwards them as
notifications. Keeping this decoupled means tools never print anything.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

log = logging.getLogger("sheetagent.events")

#: logging.LogRecord owns these names; a colliding key raises at log time.
_RESERVED_LOG_KEYS = {"args", "msg", "message", "name", "levelname", "levelno",
                      "pathname", "filename", "module", "exc_info", "exc_text",
                      "stack_info", "lineno", "funcName", "created", "msecs",
                      "relativeCreated", "thread", "threadName", "process",
                      "processName", "asctime", "taskName"}


def _safe_extra(data: dict[str, Any]) -> dict[str, Any]:
    return {(f"x_{k}" if k in _RESERVED_LOG_KEYS else k): v for k, v in data.items()}

EventKind = Literal[
    "run_started", "plan_ready", "step_started", "step_progress",
    "step_succeeded", "step_failed", "run_finished", "assistant_message",
]


@dataclass
class Event:
    kind: EventKind
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)


class EventBus:
    def __init__(self) -> None:
        self._subscribers: list[Callable[[Event], None]] = []
        self.history: list[Event] = []

    def subscribe(self, fn: Callable[[Event], None]) -> None:
        self._subscribers.append(fn)

    def emit(self, kind: EventKind, message: str, **data: Any) -> Event:
        event = Event(kind=kind, message=message, data=data)
        self.history.append(event)
        log.info(message, extra={"event": kind, **_safe_extra(data)})
        for fn in self._subscribers:
            try:
                fn(event)
            except Exception:  # a broken subscriber must not kill the run
                log.exception("event subscriber raised")
        return event
