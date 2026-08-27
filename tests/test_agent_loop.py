"""End-to-end agent tests with a stubbed Anthropic client - no network, no key."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from sheetagent.agent import MissingCredentials, SheetAgent
from tests.support.deterministic_planner import deterministic_test_planner


@dataclass
class TextBlock:
    text: str
    type: str = "text"


@dataclass
class ToolUseBlock:
    name: str
    input: dict
    id: str = "tu_1"
    type: str = "tool_use"


@dataclass
class FakeResponse:
    content: list


class FakeClient:
    """Replays a scripted sequence of model responses."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        # snapshot: the executor mutates its message list in place
        self.calls.append({**kwargs, "messages": list(kwargs.get("messages", []))})
        return self.script.pop(0)


def test_agent_runs_plan_then_tools(config, monkeypatch):
    plan_json = json.dumps({
        "goal": "csv to excel",
        "steps": [{"n": 1, "tool": "generate_employee_csv", "intent": "make data",
                   "inputs": {"row_count": 20}},
                  {"n": 2, "tool": "import_csv_to_excel", "intent": "excel"}],
        "risks": ["Excel may be missing"],
    })
    client = FakeClient([
        FakeResponse([TextBlock(plan_json)]),                                  # planner
        FakeResponse([ToolUseBlock("generate_employee_csv", {"row_count": 20})]),
        FakeResponse([TextBlock("All steps completed successfully.")]),
    ])
    config.agent.enabled_tools = ["generate_employee_csv", "import_csv_to_excel"]
    agent = SheetAgent(config=config, client=client)
    result = agent.run("Create an employee CSV and import it into Excel.")

    assert result.plan is not None
    assert [s.tool for s in result.plan.steps] == [
        "generate_employee_csv", "import_csv_to_excel"]
    assert result.steps[0]["status"] == "success"
    assert Path(result.artifacts["csv_path"]).exists()
    assert "completed" in result.report
    # planner call must not carry tools; executor call must
    assert "tools" not in client.calls[0]
    assert client.calls[1]["tools"]


def test_tool_failure_is_surfaced_to_the_model(config):
    plan_json = json.dumps({"goal": "g", "steps": [
        {"n": 1, "tool": "import_csv_to_excel", "intent": "excel"}], "risks": []})
    client = FakeClient([
        FakeResponse([TextBlock(plan_json)]),
        FakeResponse([ToolUseBlock("import_csv_to_excel", {"csv_path": "/nope.csv"})]),
        FakeResponse([TextBlock("Step 1 FAILED: source CSV missing.")]),
    ])
    agent = SheetAgent(config=config, client=client)
    result = agent.run("Import /nope.csv into Excel.")
    assert result.steps[0]["status"] == "failed"
    assert result.ok is False
    # the executor must hand the failure back to the model as an error result
    tool_results = [block
                    for call in client.calls
                    for msg in call.get("messages", [])
                    if isinstance(msg.get("content"), list)
                    for block in msg["content"]
                    if isinstance(block, dict) and block.get("type") == "tool_result"]
    assert tool_results and tool_results[0]["is_error"] is True


def test_test_mode_completes_without_a_model(config):
    config.agent.enabled_tools = ["generate_employee_csv", "import_csv_to_excel"]
    agent = SheetAgent(config=config, test_planner=deterministic_test_planner)
    result = agent.run("Create an employee CSV and import it into Excel.")
    assert [s["tool"] for s in result.steps] == [
        "generate_employee_csv", "import_csv_to_excel"]
    assert all(s["status"] == "success" for s in result.steps)
    assert "SUCCESS" in result.report


def test_events_are_emitted_in_order(config):
    seen = []
    agent = SheetAgent(config=config, test_planner=deterministic_test_planner)
    agent.events.subscribe(lambda e: seen.append(e.kind))
    config.agent.enabled_tools = ["generate_employee_csv"]
    agent.run("make a csv")
    assert seen[0] == "run_started"
    assert "plan_ready" in seen
    assert seen[-1] == "run_finished"


def test_memory_persists_between_runs(config):
    config.agent.enabled_tools = ["generate_employee_csv"]
    SheetAgent(config=config, test_planner=deterministic_test_planner).run("make a csv")
    second = SheetAgent(config=config, test_planner=deterministic_test_planner)
    assert "last_csv_path" in second.memory.facts
    assert "csv" in second.memory.summary()


# --------------------------------------------------------------------------- #
# No silent downgrade: an agent that cannot reason must say so, not quietly
# run a fixed sequence and report success.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("provider,env_var", [
    ("gemini", "GEMINI_API_KEY"),
    ("anthropic", "ANTHROPIC_API_KEY"),
])
def test_missing_api_key_is_fatal(config, monkeypatch, provider, env_var):
    """Whichever provider is configured, its own key is the one named.

    Parametrized rather than hardcoded so changing the default provider is a
    one-line config change, not a test edit.
    """
    monkeypatch.delenv(env_var, raising=False)
    config.agent.provider = provider
    with pytest.raises(MissingCredentials, match=env_var):
        SheetAgent(config=config)


def test_missing_api_key_is_tolerated_only_with_an_explicit_test_planner(
        config):
    agent = SheetAgent(config=config, test_planner=deterministic_test_planner)
    assert agent.use_llm is False


def test_test_mode_plan_is_labelled_as_non_reasoning(config):
    config.agent.enabled_tools = ["generate_employee_csv"]
    agent = SheetAgent(config=config, test_planner=deterministic_test_planner)
    result = agent.run("make a csv")
    assert any("DETERMINISTIC TEST PLANNER" in r for r in result.plan.risks)
