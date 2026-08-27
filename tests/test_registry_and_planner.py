import pytest

from sheetagent.planner import Plan, PlanStep, _extract_json, parse_plan
from tests.support.deterministic_planner import deterministic_test_planner
from sheetagent.registry import REGISTRY, Tool, ToolRegistry


def test_all_tools_registered():
    for name in ("generate_employee_csv", "import_csv_to_excel",
                 "import_csv_to_google_sheets", "verify_imports"):
        assert name in REGISTRY.names()


def test_schemas_are_valid_anthropic_shape():
    for schema in REGISTRY.schemas():
        assert schema["input_schema"]["type"] == "object"
        assert schema["description"]
        assert "properties" in schema["input_schema"]


def test_enabled_filter_is_configurable():
    subset = REGISTRY.schemas(["generate_employee_csv"])
    assert [s["name"] for s in subset] == ["generate_employee_csv"]


def test_unknown_tool_returns_structured_failure(ctx):
    result = REGISTRY.execute("no_such_tool", {}, ctx)
    assert result["status"] == "failed"
    assert "unknown tool" in result["error"]


def test_raising_tool_is_caught(ctx):
    local = ToolRegistry()

    def boom(ctx):
        raise RuntimeError("kaboom")

    local.register(Tool("boom", "explodes", {"type": "object", "properties": {}}, boom))
    result = local.execute("boom", {}, ctx)
    assert result["status"] == "failed"
    assert "kaboom" in result["error"]


def test_duplicate_registration_rejected():
    local = ToolRegistry()
    spec = Tool("x", "d", {"type": "object", "properties": {}}, lambda: {})
    local.register(spec)
    with pytest.raises(ValueError):
        local.register(spec)


def test_extract_json_handles_fences():
    assert _extract_json('```json\n{"goal": "g", "steps": []}\n```')["goal"] == "g"


def test_parse_plan_drops_unknown_tools():
    payload = {"goal": "g", "steps": [
        {"n": 1, "tool": "generate_employee_csv", "intent": "make csv"},
        {"n": 2, "tool": "hallucinated_tool", "intent": "nope"}]}
    plan = parse_plan(payload, REGISTRY.names())
    assert [s.tool for s in plan.steps] == ["generate_employee_csv"]


def test_parse_plan_rejects_empty():
    with pytest.raises(ValueError):
        parse_plan({"goal": "g", "steps": []}, REGISTRY.names())


def test_deterministic_test_planner_covers_full_workflow():
    plan = deterministic_test_planner("import into excel and google sheets", REGISTRY.schemas())
    assert [s.tool for s in plan.steps] == [
        "generate_employee_csv", "import_csv_to_excel",
        "import_csv_to_google_sheets", "verify_imports"]


def test_deterministic_test_planner_skips_sheets_when_not_requested():
    plan = deterministic_test_planner("just make a csv and open it in excel", REGISTRY.schemas())
    assert "import_csv_to_google_sheets" not in [s.tool for s in plan.steps]


def test_plan_render_is_readable():
    plan = Plan("g", [PlanStep(1, "t", "why", {})], ["risk"])
    assert "1. t — why" in plan.render()
