"""Model providers.

``agent.py`` and ``planner.py`` talk to exactly one interface, the one the
Anthropic SDK already exposes:

    client.messages.create(model=..., max_tokens=..., temperature=...,
                           system=..., tools=[...], messages=[...])
        -> response.content  # list of blocks with .type == "text" | "tool_use"

Anything that satisfies that shape can drive the agent. The Anthropic client
satisfies it natively; the Gemini adapter is a translation layer that makes the
Gemini SDK satisfy it too. The tool registry stays the single source of truth
for tool schemas - a provider adapts to the registry, never the reverse.
"""
from __future__ import annotations

import os
import re
from typing import Any


class MissingCredentials(RuntimeError):
    """No usable model client and no explicit test planner.

    Deliberately fatal. The agent's whole premise is that a model chooses the
    tools, so quietly degrading to a fixed sequence would make a successful run
    mean something different than the user thinks it means.
    """


class ProviderPermanentError(RuntimeError):
    """A provider rejection that will be rejected identically on every retry."""


#: Status codes that clear up on their own. 429 and the 5xx family are the
#: whole reason model calls need a retry at all: a free-tier quota spike or a
#: "model is experiencing high demand" 503 is temporary, and abandoning a run
#: that has already done real work because of one is needless.
_TRANSIENT_STATUS = {408, 429, 500, 502, 503, 504}


def _status_of(exc: BaseException) -> int | None:
    """Best-effort HTTP status from an SDK exception.

    Anthropic and google-genai expose it differently and neither guarantees an
    attribute, so fall back to reading the code out of the message.
    """
    for attr in ("status_code", "code"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    if isinstance(value, int):
        return value
    match = re.search(r"\b([45]\d\d)\b", str(exc))
    return int(match.group(1)) if match else None


def classify_provider_error(exc: BaseException) -> BaseException:
    """Transient errors pass through to be retried; the rest short-circuit."""
    status = _status_of(exc)
    if status in _TRANSIENT_STATUS:
        return exc
    if status is not None and 400 <= status < 500:
        return ProviderPermanentError(f"provider rejected the request: {exc}")
    return exc


#: provider name -> (env var holding the key, human-readable install hint)
PROVIDERS = {
    "anthropic": ("ANTHROPIC_API_KEY", "pip install anthropic"),
    "gemini": ("GEMINI_API_KEY", "pip install google-genai"),
}


def make_client(provider: str) -> Any:
    """Build a client for ``provider``, or raise MissingCredentials."""
    provider = (provider or "anthropic").lower()
    if provider not in PROVIDERS:
        raise MissingCredentials(
            f"unknown agent.provider {provider!r}; "
            f"expected one of {', '.join(sorted(PROVIDERS))}")

    env_var, install_hint = PROVIDERS[provider]
    if not os.environ.get(env_var):
        raise MissingCredentials(
            f"{env_var} is not set, so the agent cannot plan or choose tools. "
            f"Set the key, or pass --test-mode to run the fixed deterministic "
            f"plan used by CI (which does no reasoning).")

    if provider == "anthropic":
        try:
            import anthropic
        except ImportError as exc:
            raise MissingCredentials(
                f"the anthropic package is not installed; {install_hint}") from exc
        return anthropic.Anthropic()

    from .gemini import GeminiClient
    return GeminiClient(api_key=os.environ[env_var])
