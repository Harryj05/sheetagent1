"""Conversation memory.

Two layers, with deliberately different retention:

  * **facts** - a small key/value dict (last CSV path, last spreadsheet URL).
    Kept in full and forever. This is what makes "re-import the file you made
    last time" work, and it costs a handful of tokens.
  * **messages** - the transcript. Capped hard on the way in *and* on the way
    out, because this is the part that grows without bound.

Replaying the whole transcript would make every run pay for every previous one:
run 5 would carry runs 1-4 in its prompt. Two limits prevent that:

  * ``_sanitize`` strips stored content down to what is useful later. A
    ``tool_result`` block is reduced to its ``status`` and ``summary`` - the
    full payload (row previews, column lists, byte counts) is already on disk in
    the artifacts and the JSONL log, and is worthless as prompt context a run
    later.
  * ``replay`` hands back only the last ``replay_exchanges`` user/assistant
    pairs, so the executor's input is bounded by a constant, not by history.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger("sheetagent.memory")


#: Fields worth carrying forward from a tool result. Everything else is noise
#: once the run that produced it is over.
_KEPT_RESULT_FIELDS = ("status", "summary", "error")


class ConversationMemory:
    def __init__(self, path: str | Path, max_turns: int = 40,
                 replay_exchanges: int = 2) -> None:
        self.path = Path(path)
        self.max_turns = max_turns
        #: Number of user/assistant pairs replayed into a new run.
        self.replay_exchanges = replay_exchanges
        self.messages: list[dict[str, Any]] = []
        self.facts: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.messages = data.get("messages", [])
            self.facts = data.get("facts", {})
            log.debug("loaded memory", extra={"turns": len(self.messages)})
        except Exception as exc:
            log.warning("could not read memory file, starting fresh: %s", exc)

    @staticmethod
    def _shrink_tool_result(block: dict[str, Any]) -> dict[str, Any]:
        """Reduce a tool_result block to status + summary (+ error)."""
        payload = block.get("content")
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except (ValueError, TypeError):
                payload = {"summary": payload[:200]}
        if not isinstance(payload, dict):
            payload = {"summary": str(payload)[:200]}
        slim = {k: payload[k] for k in _KEPT_RESULT_FIELDS if k in payload}
        return {**{k: v for k, v in block.items() if k != "content"},
                "content": json.dumps(slim or {"status": "unknown"}, default=str)}

    @classmethod
    def _sanitize(cls, content: Any) -> Any:
        """Strip a stored message down to what is worth replaying.

        Applied on the way *in* so an oversized payload is never written to
        disk, rather than filtered on the way out where a later reader could
        forget to call it.
        """
        if isinstance(content, str):
            return content
        if not isinstance(content, list):
            return str(content)
        cleaned = []
        for block in content:
            if not isinstance(block, dict):
                # SDK response objects - keep their text, drop the rest.
                text = getattr(block, "text", None)
                if text:
                    cleaned.append({"type": "text", "text": text})
                continue
            if block.get("type") == "tool_result":
                cleaned.append(cls._shrink_tool_result(block))
            elif block.get("type") == "text":
                cleaned.append(block)
            # tool_use blocks are dropped: a call is meaningless without its
            # result, and the result is already summarised above.
        return cleaned

    def add(self, role: str, content: Any) -> None:
        self.messages.append({"role": role, "content": self._sanitize(content)})
        if len(self.messages) > self.max_turns:
            self.messages = self.messages[-self.max_turns:]

    def replay(self) -> list[dict[str, Any]]:
        """The bounded slice of history handed to the model for a new run.

        Bounded by ``replay_exchanges``, not by how many runs came before, so
        the executor's input size is constant across a long-lived memory file.
        The first replayed message must be a 'user' turn - the API rejects a
        history that opens with an assistant message.
        """
        window = self.messages[-(self.replay_exchanges * 2):]
        while window and window[0].get("role") != "user":
            window = window[1:]
        return [dict(m) for m in window]

    def remember(self, key: str, value: Any) -> None:
        self.facts[key] = value

    def summary(self) -> str:
        if not self.facts:
            return "No prior runs recorded."
        return "\n".join(f"- {k}: {v}" for k, v in self.facts.items())

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(
                json.dumps({"messages": self.messages, "facts": self.facts},
                           indent=2, default=str),
                encoding="utf-8",
            )
        except Exception as exc:
            log.warning("could not persist memory: %s", exc)
