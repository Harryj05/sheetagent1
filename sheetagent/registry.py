"""Tool registry and execution context.

Tools are plain functions decorated with @tool. The registry turns them into
Anthropic tool-calling schemas and executes them defensively: a tool that
raises produces a structured failure result instead of aborting the run.
"""
from __future__ import annotations

import inspect
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from .config import Config
from .events import EventBus

log = logging.getLogger("sheetagent.registry")


@dataclass
class ToolContext:
    """Everything a tool is allowed to touch. Passed explicitly - no globals."""
    config: Config
    events: EventBus
    #: Cross-tool scratch space, e.g. the CSV path produced by an earlier step.
    state: dict[str, Any] = field(default_factory=dict)


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    fn: Callable[..., dict[str, Any]]

    def to_anthropic(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description,
                "input_schema": self.input_schema}


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"duplicate tool name: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise KeyError(name)
        return self._tools[name]

    def names(self) -> list[str]:
        return list(self._tools)

    def enabled(self, allow: list[str] | None) -> list[Tool]:
        if not allow:
            return list(self._tools.values())
        return [self._tools[n] for n in allow if n in self._tools]

    def schemas(self, allow: list[str] | None = None) -> list[dict[str, Any]]:
        return [t.to_anthropic() for t in self.enabled(allow)]

    def execute(self, name: str, args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
        started = time.time()
        ctx.events.emit("step_started", f"Running {name}", tool=name, args=args)
        try:
            tool = self.get(name)
        except KeyError:
            result = {"status": "failed", "tool": name,
                      "error": f"unknown tool '{name}'",
                      "available": self.names()}
            ctx.events.emit("step_failed", f"Unknown tool {name}", tool=name)
            return result

        try:
            sig = inspect.signature(tool.fn)
            kwargs = dict(args)
            if "ctx" in sig.parameters:
                kwargs["ctx"] = ctx
            payload = tool.fn(**kwargs)
            payload.setdefault("status", "success")
            payload["tool"] = name
            payload["duration_s"] = round(time.time() - started, 3)
            kind = "step_succeeded" if payload["status"] == "success" else "step_failed"
            ctx.events.emit(kind, payload.get("summary", f"{name} {payload['status']}"),
                            tool=name, **{"result": payload})
            return payload
        except Exception as exc:  # graceful degradation - report, never crash
            log.exception("tool %s raised", name)
            payload = {
                "status": "failed",
                "tool": name,
                "error": f"{type(exc).__name__}: {exc}",
                "duration_s": round(time.time() - started, 3),
                "hint": "Inspect logs/agent.jsonl for the traceback.",
            }
            ctx.events.emit("step_failed", f"{name} failed: {exc}", tool=name)
            return payload


REGISTRY = ToolRegistry()


def tool(name: str, description: str, input_schema: dict[str, Any],
         registry: ToolRegistry | None = None):
    """Decorator registering a function as an agent-callable tool."""
    def wrapper(fn: Callable[..., dict[str, Any]]):
        (registry or REGISTRY).register(
            Tool(name=name, description=description, input_schema=input_schema, fn=fn)
        )
        return fn
    return wrapper
