"""Gemini adapter.

Presents the Anthropic ``client.messages.create(...) -> response.content``
interface on top of the Gemini SDK, so ``agent.py`` and ``planner.py`` are
provider-agnostic and need no branching.

Three translations happen here, and nowhere else:

1. **Tool schemas.** The registry's Anthropic-style ``input_schema`` becomes a
   Gemini ``functionDeclaration.parameters``. The registry stays authoritative;
   this only reshapes what it already produced.
2. **Conversation.** Anthropic ``messages`` (with ``tool_use`` / ``tool_result``
   blocks) become Gemini ``contents`` (with ``functionCall`` /
   ``functionResponse`` parts).
3. **Response.** Gemini parts become blocks exposing ``.type``, ``.text``,
   ``.name``, ``.input`` and ``.id`` - exactly what the executor loop reads.

Tool-call ids: Anthropic issues one per call and the agent echoes it back on the
matching ``tool_result``. Gemini has no such id, and its ``functionResponse`` is
keyed by function *name*. The id is therefore synthesised as ``"<name>::<n>"``
so the name can be recovered from it without the adapter holding cross-call
state.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("sheetagent.providers.gemini")

ID_SEPARATOR = "::"

#: JSON Schema keys Gemini's functionDeclaration parser rejects or ignores.
_UNSUPPORTED_SCHEMA_KEYS = {"default", "additionalProperties", "$schema",
                            "title", "examples"}


# --------------------------------------------------------------------------- #
# Response blocks - duck-typed to match the Anthropic SDK's content blocks
# --------------------------------------------------------------------------- #
@dataclass
class TextBlock:
    text: str
    type: str = "text"


@dataclass
class ToolUseBlock:
    name: str
    input: dict[str, Any]
    id: str
    type: str = "tool_use"


@dataclass
class Response:
    content: list[Any] = field(default_factory=list)
    stop_reason: str | None = None


def tool_use_id(name: str, index: int) -> str:
    return f"{name}{ID_SEPARATOR}{index}"


def name_from_tool_use_id(value: str) -> str:
    return str(value).split(ID_SEPARATOR)[0]


# --------------------------------------------------------------------------- #
# 1. Tool schema translation
# --------------------------------------------------------------------------- #
def clean_schema(schema: Any) -> Any:
    """Recursively drop keys Gemini's schema parser will not accept."""
    if isinstance(schema, list):
        return [clean_schema(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    return {k: clean_schema(v) for k, v in schema.items()
            if k not in _UNSUPPORTED_SCHEMA_KEYS}


def to_function_declarations(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Anthropic tool schemas -> Gemini functionDeclarations."""
    declarations = []
    for tool in tools or []:
        parameters = clean_schema(tool.get("input_schema") or {})
        # Gemini rejects an OBJECT schema that declares no properties.
        if not parameters.get("properties"):
            parameters = None
        declarations.append({
            "name": tool["name"],
            "description": tool.get("description", ""),
            **({"parameters": parameters} if parameters else {}),
        })
    return declarations


# --------------------------------------------------------------------------- #
# 2. Conversation translation
# --------------------------------------------------------------------------- #
def _block_to_part(block: Any) -> dict[str, Any] | None:
    if not isinstance(block, dict):
        # An SDK response object echoed back into the history by the agent.
        kind = getattr(block, "type", None)
        if kind == "text":
            return {"text": getattr(block, "text", "")}
        if kind == "tool_use":
            return {"function_call": {"name": getattr(block, "name", ""),
                                      "args": dict(getattr(block, "input", {}) or {})}}
        return None

    kind = block.get("type")
    if kind == "text":
        return {"text": block.get("text", "")}
    if kind == "tool_use":
        return {"function_call": {"name": block.get("name", ""),
                                  "args": dict(block.get("input") or {})}}
    if kind == "tool_result":
        payload = block.get("content")
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (ValueError, TypeError):
                payload = {"result": payload}
        if not isinstance(payload, dict):
            payload = {"result": payload}
        return {"function_response": {
            "name": name_from_tool_use_id(block.get("tool_use_id", "")),
            "response": payload}}
    return None


def to_contents(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Anthropic messages -> Gemini contents."""
    contents: list[dict[str, Any]] = []
    for message in messages:
        # Gemini calls the assistant "model"; a functionResponse is a user turn.
        role = "model" if message.get("role") == "assistant" else "user"
        content = message.get("content")
        if isinstance(content, str):
            parts: list[dict[str, Any]] = [{"text": content}]
        else:
            parts = [p for p in (_block_to_part(b) for b in content or []) if p]
        if parts:
            contents.append({"role": role, "parts": parts})
    return contents


# --------------------------------------------------------------------------- #
# 3. Response translation
# --------------------------------------------------------------------------- #
def _parts_of(response: Any) -> list[Any]:
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        return []
    content = getattr(candidates[0], "content", None)
    return list(getattr(content, "parts", None) or [])


def from_response(response: Any) -> Response:
    """Gemini response -> blocks the executor loop already understands."""
    blocks: list[Any] = []
    for index, part in enumerate(_parts_of(response)):
        call = getattr(part, "function_call", None)
        if call is not None:
            name = getattr(call, "name", "") or ""
            args = getattr(call, "args", None) or {}
            blocks.append(ToolUseBlock(name=name, input=dict(args),
                                       id=tool_use_id(name, index)))
            continue
        text = getattr(part, "text", None)
        if text:
            blocks.append(TextBlock(text=text))
    candidates = getattr(response, "candidates", None) or []
    stop = getattr(candidates[0], "finish_reason", None) if candidates else None
    return Response(content=blocks, stop_reason=str(stop) if stop else None)


# --------------------------------------------------------------------------- #
# Client
# --------------------------------------------------------------------------- #
class _Messages:
    def __init__(self, client: "GeminiClient") -> None:
        self._client = client

    def create(self, *, model: str, messages: list[dict[str, Any]],
               max_tokens: int | None = None, temperature: float | None = None,
               system: str | None = None,
               tools: list[dict[str, Any]] | None = None,
               **_ignored: Any) -> Response:
        config: dict[str, Any] = {}
        if max_tokens is not None:
            config["max_output_tokens"] = max_tokens
        if temperature is not None:
            config["temperature"] = temperature
        if system:
            config["system_instruction"] = system
        declarations = to_function_declarations(tools)
        if declarations:
            config["tools"] = [{"function_declarations": declarations}]

        raw = self._client.generate(model=model, contents=to_contents(messages),
                                    config=config)
        return from_response(raw)


class GeminiClient:
    """Anthropic-shaped facade over the Gemini SDK."""

    def __init__(self, api_key: str, sdk_client: Any | None = None) -> None:
        self._sdk = sdk_client
        self._api_key = api_key
        self.messages = _Messages(self)

    def _ensure_sdk(self) -> Any:
        if self._sdk is None:
            try:
                from google import genai
            except ImportError as exc:  # pragma: no cover - import-time only
                raise RuntimeError(
                    "google-genai is not installed; pip install google-genai"
                ) from exc
            self._sdk = genai.Client(api_key=self._api_key)
        return self._sdk

    def generate(self, *, model: str, contents: list[dict[str, Any]],
                 config: dict[str, Any]) -> Any:
        """Isolated so tests can stub one method instead of the whole SDK."""
        return self._ensure_sdk().models.generate_content(
            model=model, contents=contents, config=config)
