"""A fixed, non-reasoning planner used ONLY by tests and CI.

This deliberately lives under ``tests/`` and not in the ``sheetagent`` package.
It selects tools by substring-matching the prompt, which is precisely the
hardcoded step selection the agent is designed NOT to do - the real planner
(``sheetagent.planner.make_plan``) asks the model for an ordered plan and
validates the tool names it returns.

Keeping it here makes the boundary unambiguous: the shipped agent has exactly
one way to decide what to run, and it involves a model. This exists so the
tool layer, the executor, retries and verification can be exercised without an
API key, and so CI does not need network access.

It is reachable from the CLI only via the explicitly named ``--test-mode``
flag.
"""
from __future__ import annotations

from typing import Any

from sheetagent.planner import Plan, PlanStep

WORKFLOW_ORDER = [
    "generate_employee_csv",
    "import_csv_to_excel",
    "import_csv_to_google_sheets",
    "verify_imports",
]


def deterministic_test_planner(request: str, tools: list[dict[str, Any]]) -> Plan:
    """Return a fixed plan. Not a fallback - a test double.

    Never call this from product code; ``SheetAgent`` accepts it only through
    its ``test_planner`` argument.
    """
    names = [t["name"] for t in tools]
    lowered = request.lower()
    steps: list[PlanStep] = []
    n = 1
    for name in WORKFLOW_ORDER:
        if name not in names:
            continue
        if name == "import_csv_to_excel" and "excel" not in lowered and "both" not in lowered:
            continue
        if name == "import_csv_to_google_sheets" and not any(
                k in lowered for k in ("google", "sheet", "both")):
            continue
        steps.append(PlanStep(n=n, tool=name,
                              intent=f"deterministic test plan step: {name}",
                              inputs={}))
        n += 1
    return Plan(goal=request, steps=steps,
                risks=["DETERMINISTIC TEST PLANNER - no model reasoning was applied"])
