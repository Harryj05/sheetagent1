"""Multi-step planning.

Before touching anything, the agent asks the model for an explicit plan: an
ordered list of steps naming the tool each will use and why. The plan is shown
to the user, stored in memory, and fed back into the execution prompt so the
executor has a commitment to follow (and to revise out loud if a step fails).
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, asdict
from typing import Any

log = logging.getLogger("sheetagent.planner")

PLANNER_SYSTEM = """You are the planning stage of an autonomous spreadsheet agent.

Given a user request and the list of available tools, produce a short ordered
plan. Only use tools from the provided list. Do not invent steps that no
available tool can perform. Prefer the smallest plan that fully satisfies the
request, and always finish with a verification step when a verification tool
exists.

Respond with JSON only, in this shape:
{"goal": "...",
 "steps": [{"n": 1, "tool": "tool_name", "intent": "why this step exists",
            "inputs": {"key": "value"}}],
 "risks": ["things that could fail and how you will respond"]}"""


@dataclass
class PlanStep:
    n: int
    tool: str
    intent: str
    inputs: dict[str, Any]


@dataclass
class Plan:
    goal: str
    steps: list[PlanStep]
    risks: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {"goal": self.goal, "steps": [asdict(s) for s in self.steps],
                "risks": self.risks}

    def render(self) -> str:
        lines = [f"Goal: {self.goal}", "Plan:"]
        lines += [f"  {s.n}. {s.tool} — {s.intent}" for s in self.steps]
        if self.risks:
            lines.append("Risks: " + "; ".join(self.risks))
        return "\n".join(lines)


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in planner response")
    return json.loads(text[start:end + 1])


def parse_plan(payload: dict[str, Any], valid_tools: list[str]) -> Plan:
    steps: list[PlanStep] = []
    for i, raw in enumerate(payload.get("steps", []), start=1):
        name = raw.get("tool", "")
        if name not in valid_tools:
            log.warning("planner proposed unknown tool %r; dropping step", name)
            continue
        steps.append(PlanStep(n=raw.get("n", i), tool=name,
                              intent=raw.get("intent", ""),
                              inputs=raw.get("inputs", {}) or {}))
    if not steps:
        raise ValueError("plan contained no usable steps")
    return Plan(goal=payload.get("goal", ""), steps=steps,
                risks=list(payload.get("risks", [])))


def make_plan(client, model: str, request: str, tools: list[dict[str, Any]],
              memory_summary: str = "", call_model=None) -> Plan:
    """Ask the model for a plan.

    ``call_model`` lets the agent inject its own retrying caller, so a 503 on
    the planning turn does not lose the run before any work has started. It
    falls back to a plain client call when not supplied.
    """
    catalog = "\n".join(f"- {t['name']}: {t['description']}" for t in tools)
    user = (f"User request:\n{request}\n\nAvailable tools:\n{catalog}"
            + (f"\n\nContext from earlier runs:\n{memory_summary}" if memory_summary else ""))
    messages = [{"role": "user", "content": user}]
    if call_model is not None:
        response = call_model(system=PLANNER_SYSTEM, messages=messages,
                              label="planner")
    else:
        response = client.messages.create(
            model=model, max_tokens=1200, temperature=0,
            system=PLANNER_SYSTEM, messages=messages,
        )
    text = "".join(b.text for b in response.content if getattr(b, "type", "") == "text")
    return parse_plan(_extract_json(text), [t["name"] for t in tools])
