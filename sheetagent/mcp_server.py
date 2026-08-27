"""Expose the same tools over MCP (stdio) so Claude Desktop / Claude Code can
drive the workflow directly - the tool implementations are shared, not copied.

    python -m sheetagent.mcp_server
"""
from __future__ import annotations

import inspect
import json
import logging

try:  # mcp >= 2.0 renamed FastMCP to MCPServer
    from mcp.server.mcpserver import MCPServer as _MCPServer
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _MCPServer

from .config import Config
from .events import EventBus
from .logging_setup import setup_logging
from .registry import REGISTRY, ToolContext
from . import tools  # noqa: F401  - registration side effect

log = logging.getLogger("sheetagent.mcp")

setup_logging(log_dir=Config.load().log_dir)
mcp = _MCPServer("sheetagent")

_CONFIG = Config.load()
_CTX = ToolContext(config=_CONFIG, events=EventBus())


_JSON_TO_PY = {"string": str, "integer": int, "number": float,
               "boolean": bool, "array": list, "object": dict}


def _signature_from_schema(schema: dict) -> inspect.Signature:
    """Project our JSON Schema onto a real Python signature.

    The MCP server derives each tool's input schema by introspecting the
    handler, so a bare ``**kwargs`` handler advertises a single opaque
    ``kwargs`` argument and no client can call the tool correctly. Building the
    signature from the registry schema keeps the MCP surface identical to the
    one the Anthropic tool-calling loop sees.
    """
    props = schema.get("properties", {})
    required = set(schema.get("required", []))
    params = []
    for field, spec in props.items():
        annotation = _JSON_TO_PY.get(spec.get("type"), str)
        if field in required:
            default = inspect.Parameter.empty
        else:
            default = spec.get("default", None)
            annotation = annotation | None
        params.append(inspect.Parameter(
            field, inspect.Parameter.KEYWORD_ONLY,
            annotation=annotation, default=default))
    # required first, so the signature is valid
    params.sort(key=lambda p: p.default is not inspect.Parameter.empty)
    return inspect.Signature(params, return_annotation=str)


def _register(tool_name: str) -> None:
    spec = REGISTRY.get(tool_name)

    async def handler(**kwargs) -> str:
        supplied = {k: v for k, v in kwargs.items() if v is not None}
        return json.dumps(REGISTRY.execute(spec.name, supplied, _CTX),
                          indent=2, default=str)

    handler.__name__ = spec.name
    handler.__doc__ = spec.description
    handler.__signature__ = _signature_from_schema(spec.input_schema)
    handler.__annotations__ = {
        p.name: p.annotation for p in handler.__signature__.parameters.values()
    } | {"return": str}
    mcp.add_tool(handler, name=spec.name, description=spec.description)


for _name in _CONFIG.agent.enabled_tools:
    if _name in REGISTRY.names():
        _register(_name)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
