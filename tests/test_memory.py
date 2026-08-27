"""Memory retention: facts are kept, transcript growth is bounded."""
from __future__ import annotations

import json

from sheetagent.memory import ConversationMemory


def _fat_tool_result(run: int) -> list[dict]:
    """A realistic tool_result: the payload dwarfs the useful part."""
    payload = {
        "status": "success",
        "summary": f"Generated 20 employee rows (run {run})",
        "csv_path": f"C:/very/long/path/run{run}/employees.csv",
        "row_count": 20,
        "columns": ["Employee ID", "Name", "Department", "Email", "Salary",
                    "Job Title", "Location", "Hire Date", "Manager"],
        "preview": [{"Employee ID": f"EMP{i:03d}", "Name": "Somebody Withaname",
                     "Department": "Engineering", "Email": "x" * 40,
                     "Salary": 100000} for i in range(3)],
    }
    return [{"type": "tool_result", "tool_use_id": f"tu_{run}",
             "content": json.dumps(payload), "is_error": False}]


def _simulate_runs(memory: ConversationMemory, count: int) -> None:
    for run in range(count):
        memory.add("user", f"Run {run}: create an employee CSV and import it. "
                           + "context padding " * 40)
        memory.add("user", _fat_tool_result(run))
        memory.add("assistant", f"Workflow report for run {run}\n" + "detail " * 60)


def _size(messages) -> int:
    return len(json.dumps(messages, default=str))


def test_replay_is_bounded_across_ten_runs(tmp_path):
    """Run 10 must not pay for runs 1-9."""
    memory = ConversationMemory(tmp_path / "m.json")

    _simulate_runs(memory, 1)
    after_one = _size(memory.replay())

    _simulate_runs(memory, 9)
    after_ten = _size(memory.replay())

    assert after_ten <= after_one * 2, (
        f"replay grew with history: {after_one} -> {after_ten} bytes")
    assert after_ten < 2000, f"replay is not bounded by a small constant: {after_ten}"
    assert len(memory.replay()) <= memory.replay_exchanges * 2


def test_replay_grows_no_further_after_fifty_runs(tmp_path):
    memory = ConversationMemory(tmp_path / "m.json")
    _simulate_runs(memory, 10)
    ten = _size(memory.replay())
    _simulate_runs(memory, 40)
    fifty = _size(memory.replay())
    assert fifty == ten or abs(fifty - ten) < 400, (
        f"replay still drifting with history: {ten} -> {fifty}")


def test_tool_result_payloads_are_stripped_to_status_and_summary(tmp_path):
    memory = ConversationMemory(tmp_path / "m.json")
    memory.add("user", _fat_tool_result(1))
    stored = memory.messages[-1]["content"][0]
    payload = json.loads(stored["content"])

    assert set(payload) <= {"status", "summary", "error"}
    assert payload["status"] == "success"
    assert "Generated 20 employee rows" in payload["summary"]
    assert "preview" not in stored["content"]
    assert "tool_use_id" in stored, "the block must stay a valid tool_result"


def test_facts_survive_untouched(tmp_path):
    """The cap applies to the transcript, never to the facts dict."""
    memory = ConversationMemory(tmp_path / "m.json")
    memory.remember("last_csv_path", "C:/out/employees.csv")
    memory.remember("last_spreadsheet_url", "https://docs.google.com/x")
    _simulate_runs(memory, 20)
    memory.save()

    reloaded = ConversationMemory(tmp_path / "m.json")
    assert reloaded.facts["last_csv_path"] == "C:/out/employees.csv"
    assert reloaded.facts["last_spreadsheet_url"] == "https://docs.google.com/x"
    assert "last_csv_path" in reloaded.summary()


def test_replay_never_opens_with_an_assistant_turn(tmp_path):
    """The Messages API rejects a history whose first turn is the assistant."""
    memory = ConversationMemory(tmp_path / "m.json", replay_exchanges=1)
    memory.add("user", "hello")
    memory.add("assistant", "hi")
    memory.add("assistant", "still me")
    replay = memory.replay()
    assert replay == [] or replay[0]["role"] == "user"


def test_stored_transcript_stays_small_on_disk(tmp_path):
    memory = ConversationMemory(tmp_path / "m.json")
    _simulate_runs(memory, 50)
    memory.save()
    assert len(memory.messages) <= memory.max_turns
    assert (tmp_path / "m.json").stat().st_size < 60_000
