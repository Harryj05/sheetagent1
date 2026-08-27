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
from typing import Any


class MissingCredentials(RuntimeError):
    """No usable model client and no explicit test planner.

    Deliberately fatal. The agent's whole premise is that a model chooses the
    tools, so quietly degrading to a fixed sequence would make a successful run
    mean something different than the user thinks it means.
    """


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
