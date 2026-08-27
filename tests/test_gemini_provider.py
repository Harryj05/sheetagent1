"""Gemini adapter tests.

The Gemini SDK is stubbed at exactly one seam - GeminiClient.generate - the same
way test_agent_loop.py stubs the Anthropic client. No network, no key.

The point of these tests is that agent.py sees no difference: the same executor
loop, driven by a Gemini response, must produce the same steps and the same
report as it does under Anthropic.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from sheetagent.agent import MissingCredentials, SheetAgent
from sheetagent.providers import make_client
from sheetagent.providers.gemini import (
    GeminiClient,
    ToolUseBlock,
    clean_schema,
    from_response,
    name_from_tool_use_id,
    to_contents,
    to_function_declarations,
)
from sheetagent.registry import REGISTRY


# --------------------------------------------------------------------------- #
# Fakes shaped like the google-genai response objects
# --------------------------------------------------------------------------- #
@dataclass
class FakeFunctionCall:
    name: str
    args: dict[str, Any]


@dataclass
class FakePart:
    text: str | None = None
    function_call: FakeFunctionCall | None = None


@dataclass
class FakeContent:
    parts: list[FakePart] = field(default_factory=list)


@dataclass
class FakeCandidate:
    content: FakeContent
    finish_reason: str | None = "STOP"


@dataclass
class FakeGeminiResponse:
    candidates: list[FakeCandidate]


def _response(*parts: FakePart) -> FakeGeminiResponse:
    return FakeGeminiResponse(candidates=[FakeCandidate(FakeContent(list(parts)))])


def _plan_response(*tools: str) -> FakeGeminiResponse:
    """The planner turn. It consumes the first response, exactly as it does
    under Anthropic - the adapter changes the transport, not the flow."""
    return _response(FakePart(text=json.dumps({
        "goal": "test plan",
        "steps": [{"n": i, "tool": t, "intent": "step", "inputs": {}}
                  for i, t in enumerate(tools, start=1)],
        "risks": [],
    })))


class ScriptedGemini(GeminiClient):
    """Replays a fixed list of Gemini responses and records what it was sent."""

    def __init__(self, responses: list[FakeGeminiResponse]) -> None:
        super().__init__(api_key="test-key", sdk_client=object())
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def generate(self, *, model, contents, config):
        self.calls.append({"model": model, "contents": contents, "config": config})
        return self._responses.pop(0)


# --------------------------------------------------------------------------- #
# 1. Tool schema translation - the registry stays the source of truth
# --------------------------------------------------------------------------- #
def test_declarations_are_derived_from_the_registry():
    schemas = REGISTRY.schemas()
    declarations = to_function_declarations(schemas)

    assert [d["name"] for d in declarations] == [s["name"] for s in schemas]
    for schema, declaration in zip(schemas, declarations):
        assert declaration["description"] == schema["description"]
        assert set(declaration["parameters"]["properties"]) == \
            set(schema["input_schema"]["properties"])
        assert declaration["parameters"].get("required") == \
            schema["input_schema"].get("required")


def test_unsupported_schema_keys_are_stripped_recursively():
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "fmt": {"type": "string", "default": "xlsx", "enum": ["xlsx", "ods"]},
            "nested": {"type": "object",
                       "properties": {"n": {"type": "integer", "default": 1}}},
        },
        "required": ["fmt"],
    }
    cleaned = clean_schema(schema)

    assert "additionalProperties" not in cleaned
    assert "default" not in cleaned["properties"]["fmt"]
    assert "default" not in cleaned["properties"]["nested"]["properties"]["n"]
    # Meaning is preserved - only the unsupported keys go.
    assert cleaned["properties"]["fmt"]["enum"] == ["xlsx", "ods"]
    assert cleaned["required"] == ["fmt"]


def test_parameterless_tool_omits_parameters():
    """Gemini rejects an OBJECT schema declaring no properties."""
    declarations = to_function_declarations(
        [{"name": "ping", "description": "d", "input_schema": {"type": "object"}}])
    assert "parameters" not in declarations[0]


# --------------------------------------------------------------------------- #
# 2. Conversation translation
# --------------------------------------------------------------------------- #
def test_roles_and_blocks_are_translated():
    contents = to_contents([
        {"role": "user", "content": "make a csv"},
        {"role": "assistant", "content": [
            {"type": "text", "text": "on it"},
            {"type": "tool_use", "name": "generate_employee_csv",
             "input": {"row_count": 20}, "id": "generate_employee_csv::0"},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "generate_employee_csv::0",
             "content": json.dumps({"status": "success", "rows": 20})},
        ]},
    ])

    assert [c["role"] for c in contents] == ["user", "model", "user"]
    assert contents[1]["parts"][0] == {"text": "on it"}
    assert contents[1]["parts"][1]["function_call"] == {
        "name": "generate_employee_csv", "args": {"row_count": 20}}
    response = contents[2]["parts"][0]["function_response"]
    assert response["name"] == "generate_employee_csv"
    assert response["response"]["status"] == "success"


def test_tool_result_name_is_recovered_from_the_synthesised_id():
    assert name_from_tool_use_id("import_csv_to_excel::3") == "import_csv_to_excel"


def test_non_json_tool_result_still_produces_a_valid_function_response():
    contents = to_contents([{"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": "verify_imports::0",
         "content": "plain text, not json"}]}])
    assert contents[0]["parts"][0]["function_response"]["response"] == {
        "result": "plain text, not json"}


# --------------------------------------------------------------------------- #
# 3. Response translation
# --------------------------------------------------------------------------- #
def test_response_blocks_match_the_anthropic_shape():
    result = from_response(_response(
        FakePart(text="planning"),
        FakePart(function_call=FakeFunctionCall("import_csv_to_excel",
                                                {"csv_path": "x.csv"})),
    ))

    text, call = result.content
    assert text.type == "text" and text.text == "planning"
    assert call.type == "tool_use"
    assert call.name == "import_csv_to_excel"
    assert call.input == {"csv_path": "x.csv"}
    assert name_from_tool_use_id(call.id) == "import_csv_to_excel"


def test_empty_response_yields_no_blocks():
    assert from_response(FakeGeminiResponse(candidates=[])).content == []


# --------------------------------------------------------------------------- #
# 4. The agent loop is unchanged - same tools, same report, different provider
# --------------------------------------------------------------------------- #
def test_agent_runs_end_to_end_against_a_stubbed_gemini(config):
    config.agent.provider = "gemini"
    config.agent.model = "gemini-2.5-flash"
    config.agent.enabled_tools = ["generate_employee_csv"]

    client = ScriptedGemini([
        _plan_response("generate_employee_csv"),
        _response(FakePart(function_call=FakeFunctionCall(
            "generate_employee_csv", {"row_count": 20}))),
        _response(FakePart(text="Workflow report\n1. generate_employee_csv: SUCCESS")),
    ])
    agent = SheetAgent(config=config, client=client)
    result = agent.run("Create an employee CSV with 20 rows.")

    assert [s["tool"] for s in result.steps] == ["generate_employee_csv"]
    assert result.steps[0]["status"] == "success"
    assert result.steps[0]["row_count"] == 20
    assert "SUCCESS" in result.report


def test_tools_reach_gemini_as_function_declarations(config):
    config.agent.provider = "gemini"
    config.agent.enabled_tools = ["generate_employee_csv"]
    client = ScriptedGemini([_plan_response("generate_employee_csv"),
                             _response(FakePart(text="done"))])

    SheetAgent(config=config, client=client).run("do nothing")

    tool_config = client.calls[-1]["config"]["tools"][0]["function_declarations"]
    assert [d["name"] for d in tool_config] == ["generate_employee_csv"]
    assert "row_count" in tool_config[0]["parameters"]["properties"]


def test_system_prompt_becomes_system_instruction(config):
    config.agent.provider = "gemini"
    config.agent.enabled_tools = ["generate_employee_csv"]
    client = ScriptedGemini([_plan_response("generate_employee_csv"),
                             _response(FakePart(text="done"))])

    SheetAgent(config=config, client=client).run("do nothing")

    assert "SheetAgent" in client.calls[-1]["config"]["system_instruction"]
    assert client.calls[-1]["config"]["max_output_tokens"] == config.agent.max_tokens


def test_failed_tool_results_are_fed_back_to_gemini(config):
    """A failure must reach the model, so it can adapt rather than repeat."""
    config.agent.provider = "gemini"
    config.agent.enabled_tools = ["import_csv_to_excel"]
    client = ScriptedGemini([
        _plan_response("import_csv_to_excel"),
        _response(FakePart(function_call=FakeFunctionCall(
            "import_csv_to_excel", {"csv_path": "/nope.csv"}))),
        _response(FakePart(text="The Excel step failed.")),
    ])

    result = SheetAgent(config=config, client=client).run("import it")

    assert result.steps[0]["status"] == "failed"
    sent_back = client.calls[-1]["contents"][-1]["parts"][0]["function_response"]
    assert sent_back["name"] == "import_csv_to_excel"
    assert sent_back["response"]["status"] == "failed"


# --------------------------------------------------------------------------- #
# 5. Provider selection
# --------------------------------------------------------------------------- #
def test_gemini_selected_by_config_and_keyed_by_gemini_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    assert isinstance(make_client("gemini"), GeminiClient)


def test_missing_gemini_key_names_the_right_variable(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(MissingCredentials, match="GEMINI_API_KEY"):
        make_client("gemini")


def test_unknown_provider_is_rejected():
    with pytest.raises(MissingCredentials, match="unknown agent.provider"):
        make_client("llama")


def test_agent_honours_the_configured_provider(config, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    config.agent.provider = "gemini"
    assert isinstance(SheetAgent(config=config).client, GeminiClient)


# --------------------------------------------------------------------------- #
# Gemini 3.x thought signatures.
#
# Regression: the adapter originally dropped the opaque reasoning token Gemini
# attaches to each functionCall part. Unit tests passed and the live API
# rejected the second turn with 400 INVALID_ARGUMENT ("Function call is missing
# a thought_signature in functionCall parts"). Caught only by a real run.
# --------------------------------------------------------------------------- #
@dataclass
class SignedPart:
    text: str | None = None
    function_call: FakeFunctionCall | None = None
    thought_signature: bytes | None = None


def test_thought_signature_is_captured_from_the_response():
    result = from_response(_response(SignedPart(
        function_call=FakeFunctionCall("generate_employee_csv", {"row_count": 20}),
        thought_signature=b"sig-abc")))
    assert result.content[0].thought_signature == b"sig-abc"


def test_thought_signature_is_echoed_back_on_the_next_turn():
    """Gemini rejects the turn unless the signature is returned verbatim."""
    call = ToolUseBlock(name="generate_employee_csv", input={"row_count": 20},
                        id="generate_employee_csv::0", thought_signature=b"sig-abc")
    parts = to_contents([{"role": "assistant", "content": [call]}])[0]["parts"]
    assert parts[0]["thought_signature"] == b"sig-abc"


def test_absent_thought_signature_is_omitted_not_sent_as_none():
    """Anthropic-shaped history has no signature; sending null would be invalid."""
    call = ToolUseBlock(name="verify_imports", input={}, id="verify_imports::0")
    parts = to_contents([{"role": "assistant", "content": [call]}])[0]["parts"]
    assert "thought_signature" not in parts[0]


def test_signature_survives_a_full_executor_round_trip(config):
    """The executor replays its own history; the signature must ride along."""
    config.agent.provider = "gemini"
    config.agent.enabled_tools = ["generate_employee_csv"]
    client = ScriptedGemini([
        _plan_response("generate_employee_csv"),
        FakeGeminiResponse(candidates=[FakeCandidate(FakeContent([SignedPart(
            function_call=FakeFunctionCall("generate_employee_csv", {"row_count": 20}),
            thought_signature=b"sig-xyz")]))]),
        _response(FakePart(text="done")),
    ])
    SheetAgent(config=config, client=client).run("make a csv")

    model_turn = [c for c in client.calls[-1]["contents"] if c["role"] == "model"][-1]
    assert model_turn["parts"][0]["thought_signature"] == b"sig-xyz"
