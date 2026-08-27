# Demo video script (target 6–8 minutes)

Record on **Windows with Microsoft Excel installed** — that is the only place
the COM path can be shown. Have `credentials.json` in place, `ANTHROPIC_API_KEY` exported, and Excel
closed before you start. The agent refuses to run without the key - that is
deliberate, and worth showing.

| Time | Show | Say |
|---|---|---|
| 0:00–0:45 | `README.md` architecture diagram | The agent has four tools; a planner stage and an executor stage; nothing about the step order is hardcoded. |
| 0:45–1:30 | `sheetagent/registry.py` and one `@tool` decorator | How a Python function becomes a model-callable tool with a JSON schema, and how failures become structured results instead of crashes. |
| 1:30–3:30 | **The headline run.** `python -m sheetagent "Create a sample employee CSV and import it into Excel and Google Sheets."` | Narrate the printed plan, then each live progress line. Excel visibly launches. Let it finish and read the final report aloud. |
| 3:30–4:15 | Open `output/employees.xlsx` and the Google Sheet URL side by side | Both contain the same 20 rows; the verification step already compared them programmatically. |
| 4:15–5:00 | `python -m sheetagent "Just generate 25 employee records as a CSV. Don't open Excel."` | Only one tool call — proof the agent selects tools from the request rather than replaying a script. |
| 5:00–5:45 | Rename `credentials.json`, re-run the full prompt | Google step fails cleanly with a hint, Excel step still succeeds, the report says exactly which step failed. Restore the file. |
| 5:45–6:30 | `jq 'select(.level=="ERROR")' logs/agent.jsonl`, then `pytest -q` | Structured logs and 73 passing tests. |
| 6:30–6:50 | Unset `ANTHROPIC_API_KEY` and re-run | Exit 2 and a clear error. No silent downgrade: if the model can't choose the tools, the agent doesn't pretend to have run. `--test-mode` exists for CI only and announces itself on every run. |
| 6:50–7:20 | `config.yaml` — comment out a tool in `enabled_tools`, re-run | The agent plans around the missing tool. Close on the MCP server line. |
