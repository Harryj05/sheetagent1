"""The agent: plan, then a Claude tool-calling loop, then a structured report."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import Config
from .events import EventBus
from .memory import ConversationMemory
from .planner import Plan, make_plan
from .providers import (MissingCredentials, ProviderPermanentError,
                        classify_provider_error, make_client)
from .registry import REGISTRY, ToolContext, ToolRegistry
from .retry import with_retry

#: Re-exported: MissingCredentials moved to .providers when Gemini was
#: added, but it is part of this module's public surface.
__all__ = ["MissingCredentials", "SheetAgent", "RunResult", "render_report"]

log = logging.getLogger("sheetagent.agent")

SYSTEM_PROMPT = """You are SheetAgent, an autonomous agent that moves employee
data into spreadsheets on the user's behalf.

Rules:
* Work autonomously. Never ask the user to do a step you have a tool for, and
  never ask for confirmation mid-run.
* Follow the plan you were given, but adapt if a tool result contradicts it.
* Chain tool outputs: use the csv_path returned by generate_employee_csv as the
  input to the import tools rather than guessing a path.
* Generate at least 20 employee rows unless the user asked for a different number.
* If a tool returns status "failed", do not pretend it succeeded. Try one
  sensible alternative if the error suggests one (a different output format, a
  different engine), otherwise record the failure and continue with the steps
  that can still run.
* Finish by calling the verification tool, then write a final plain-text report
  listing every step with SUCCESS or FAILED, the file paths and URLs produced,
  and anything the user must do manually."""


@dataclass
class RunResult:
    request: str
    plan: Plan | None
    steps: list[dict[str, Any]] = field(default_factory=list)
    report: str = ""
    artifacts: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return bool(self.steps) and all(s.get("status") == "success" for s in self.steps)

    def to_dict(self) -> dict[str, Any]:
        return {"request": self.request,
                "plan": self.plan.to_dict() if self.plan else None,
                "steps": self.steps, "artifacts": self.artifacts,
                "report": self.report, "ok": self.ok}


class SheetAgent:
    def __init__(self, config: Config | None = None,
                 registry: ToolRegistry | None = None,
                 events: EventBus | None = None,
                 client: Any | None = None,
                 test_planner: Any | None = None) -> None:
        from . import tools  # noqa: F401  - registers the tools

        self.config = config or Config.load()
        self.registry = registry or REGISTRY
        self.events = events or EventBus()
        self.memory = ConversationMemory(self.config.memory_file)
        #: Set only by --test-mode / unit tests. Never populated by product code.
        self.test_planner = test_planner
        self.client = client
        if self.client is None and self.test_planner is None:
            self.client = make_client(self.config.agent.provider)

    @property
    def use_llm(self) -> bool:
        return self.client is not None

    def _call_model(self, *, system: str, messages: list[dict[str, Any]],
                    tools: list[dict[str, Any]] | None = None,
                    label: str = "model-call") -> Any:
        """One model call, with the same retry policy the tools already get.

        A 503 "model is experiencing high demand" or a 429 rate limit is
        transient, and letting one end a run that has already driven Excel is
        needless. A 4xx rejection is not retried - it will be rejected the same
        way every time.
        """
        def attempt() -> Any:
            try:
                return self.client.messages.create(
                    model=self.config.agent.model,
                    max_tokens=self.config.agent.max_tokens,
                    temperature=self.config.agent.temperature,
                    system=system,
                    **({"tools": tools} if tools else {}),
                    messages=messages,
                )
            except Exception as exc:
                raise classify_provider_error(exc) from exc

        retry = self.config.retry
        return with_retry(
            attempt,
            max_attempts=max(retry.max_attempts, 4),
            initial_delay=max(retry.initial_delay, 2.0),
            backoff=retry.backoff,
            max_delay=retry.max_delay,
            give_up_on=(ProviderPermanentError,),
            label=label,
        )

    # ------------------------------------------------------------------ #
    def run(self, request: str) -> RunResult:
        ctx = ToolContext(config=self.config, events=self.events)
        schemas = self.registry.schemas(self.config.agent.enabled_tools)
        self.events.emit("run_started", f"Request: {request}",
                         request=request, tools=[t["name"] for t in schemas],
                         mode="llm" if self.use_llm else "test-mode")

        # ---- 1. plan ---------------------------------------------------
        plan: Plan | None = None
        try:
            plan = (make_plan(self.client, self.config.agent.model, request, schemas,
                              self.memory.summary(), call_model=self._call_model)
                    if self.use_llm else self.test_planner(request, schemas))
            self.events.emit("plan_ready", plan.render(), plan=plan.to_dict())
        except Exception as exc:
            log.warning("planning failed, continuing without a plan: %s", exc)
            self.events.emit("step_progress", f"Planning failed: {exc}")

        # ---- 2. execute ------------------------------------------------
        result = (self._execute_with_llm(request, plan, schemas, ctx)
                  if self.use_llm else self._execute_plan(plan, ctx, request))

        # ---- 3. remember + report -------------------------------------
        result.artifacts = dict(ctx.state)
        for key in ("csv_path", "excel_path", "spreadsheet_url"):
            if key in ctx.state:
                self.memory.remember(f"last_{key}", ctx.state[key])
        self.memory.remember("last_request", request)
        self.memory.save()
        self.events.emit("run_finished", result.report or "Run finished",
                         ok=result.ok, artifacts=result.artifacts)
        return result

    # ------------------------------------------------------------------ #
    def _execute_with_llm(self, request: str, plan: Plan | None,
                          schemas: list[dict[str, Any]], ctx: ToolContext) -> RunResult:
        result = RunResult(request=request, plan=plan)
        content = request if plan is None else (
            f"{request}\n\nApproved plan to follow:\n{plan.render()}")
        self.memory.add("user", content)
        # Bounded slice, not the whole transcript: see ConversationMemory.replay.
        messages = self.memory.replay()

        for iteration in range(1, self.config.agent.max_iterations + 1):
            try:
                response = self._call_model(
                    system=SYSTEM_PROMPT, tools=schemas, messages=messages,
                    label=f"executor-turn-{iteration}")
            except Exception as exc:
                # A provider outage, a rate limit or an exhausted quota must not
                # dump a traceback over a run that has already done real work.
                # Whatever completed stays in result.steps and is reported.
                detail = f"{type(exc).__name__}: {exc}"
                log.error("model call failed on iteration %d: %s", iteration, detail)
                self.events.emit("step_failed", f"Model call failed: {detail}",
                                 iteration=iteration)
                done = [s for s in result.steps if s.get("status") == "success"]
                result.report = "\n".join([
                    render_report(result),
                    "",
                    "Run stopped early: the model provider returned an error "
                    f"on iteration {iteration}.",
                    f"  {detail}",
                    f"{len(done)} of {len(result.steps)} step(s) succeeded before "
                    "the failure; any output they produced is on disk.",
                ])
                result.steps.append({"tool": "(model call)", "input": {},
                                     "status": "failed", "error": detail})
                break
            text = "".join(b.text for b in response.content
                           if getattr(b, "type", "") == "text")
            if text.strip():
                self.events.emit("assistant_message", text.strip())
            messages.append({"role": "assistant", "content": response.content})

            calls = [b for b in response.content if getattr(b, "type", "") == "tool_use"]
            if not calls:
                result.report = text.strip()
                break

            tool_results = []
            for call in calls:
                payload = self.registry.execute(call.name, dict(call.input), ctx)
                result.steps.append({"tool": call.name, "input": dict(call.input),
                                     **payload})
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": call.id,
                    "content": json.dumps(payload, default=str),
                    "is_error": payload.get("status") == "failed",
                })
            messages.append({"role": "user", "content": tool_results})
            # Stored sanitised (status + summary only) so a later run inherits
            # what happened without inheriting the payloads.
            self.memory.add("user", tool_results)
        else:
            result.report = ("Stopped after reaching max_iterations "
                             f"({self.config.agent.max_iterations}).")

        self.memory.add("assistant", result.report or "(no final message)")
        return result

    def _execute_plan(self, plan: Plan | None, ctx: ToolContext,
                      request: str) -> RunResult:
        """Offline executor: runs the deterministic plan, wiring outputs forward."""
        result = RunResult(request=request, plan=plan)
        if plan is None:
            result.report = "No plan available and no model access; nothing executed."
            return result
        for step in plan.steps:
            args = dict(step.inputs)
            if step.tool != "generate_employee_csv":
                args.setdefault("csv_path", ctx.state.get("csv_path", ""))
            if step.tool == "generate_employee_csv":
                args.setdefault("row_count", 20)
            if step.tool == "verify_imports":
                args.setdefault("workbook_path", ctx.state.get("excel_path"))
                args.setdefault("spreadsheet_id", ctx.state.get("spreadsheet_id"))
            payload = self.registry.execute(step.tool, args, ctx)
            result.steps.append({"tool": step.tool, "input": args, **payload})
        result.artifacts = dict(ctx.state)
        result.report = render_report(result)
        return result


def render_report(result: RunResult) -> str:
    lines = ["Workflow report", "=" * 40]
    for i, step in enumerate(result.steps, start=1):
        status = step.get("status", "?").upper()
        lines.append(f"{i}. {step['tool']}: {status}")
        detail = step.get("summary") or step.get("error")
        if detail:
            lines.append(f"   {detail}")
    if result.artifacts:
        lines.append("")
        lines.append("Artifacts:")
        for key, value in result.artifacts.items():
            if key.endswith(("path", "url", "id")):
                lines.append(f"  {key}: {value}")
    return "\n".join(lines)
