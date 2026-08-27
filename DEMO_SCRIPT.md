# Demo video script

**Target: 7–8 minutes.** Record on **Windows with Microsoft Excel installed** —
it is the only platform where the COM path can be shown.

Everything below has been executed and verified. Nothing here is aspirational.

---

## Pre-flight (do this before hitting record)

```bash
# 1. Rebuild the virtualenv
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt

# 2. Confirm the suite is green
.venv\Scripts\python.exe -m pytest -q          # expect: 101 passed

# 3. Point at your shared Google Sheet (deliberately blank in the repo)
#    config.yaml -> sheets.spreadsheet_id: "1n5UQn1wwLNl-8ztNFa5Qy0kubuG_vMM3KfnDrc0abKU"

# 4. Confirm the key is live. This demo runs on Gemini - the verified path.
set GEMINI_API_KEY=<your key>
echo %GEMINI_API_KEY%

# config.yaml -> agent.provider: gemini / agent.model: gemini-3.6-flash
```

Checklist:

- [ ] **Close every Excel window.** A stray instance holds `output/employees.xlsx`
      open and the demo run will fail on a sharing violation.
- [ ] `del output\employees.*` so the files are visibly created on camera.
- [ ] Clear the `Employees` tab in your Google Sheet so rows appear live.
- [ ] Free disk space — you were at ~200 MB, which is not enough headroom.
- [ ] Terminal font at 16pt+. Reviewers watch this in a small window.
- [ ] Browser open on the Google Sheet in a second tab, ready to switch to.

> **One rehearsal run first.** The headline run drives real Excel and the live
> Sheets API; you want to have seen it once before recording.

---

## Shot list

| Time | Show | Say |
|---|---|---|
| **0:00–0:40** | `README.md` architecture diagram | "Four tools, two stages. A planner asks the model for an ordered plan, then an executor runs a tool-calling loop. The step order is *not* in the code — it's whatever the model decides. Swap the prompt and a different subset of tools runs." |
| **0:40–1:20** | `sheetagent/registry.py`, one `@tool` decorator | "A plain Python function becomes a model-callable tool. The registry generates the JSON schema and executes defensively — a tool that raises returns `{'status': 'failed'}` instead of killing the run. That's what makes partial failure survivable." |
| **1:20–3:30** | **The headline run** (command below) | Read the printed plan aloud. Narrate each `[OK]` line as it appears. **Excel visibly launches.** Let it finish; read the four-line report. |
| **3:30–4:20** | `output/employees.xlsx` and the Google Sheet, side by side | "Same 20 rows in both. Note the Excel workbook has a frozen header and salaries stored as numbers, not text — and the Google Sheet has its own frozen header row." |
| **4:20–4:50** | Scroll up to step 4 in the report | "Verification is a *separate tool*. It re-opens the saved workbook from disk and re-reads the live sheet through the API, then compares headers and row counts against the CSV. The agent is not allowed to mark itself correct from its own earlier output." |
| **4:50–5:30** | The CSV-only prompt | "One tool call, not four. Same code, same registry — the model read the request and chose. That's the difference between an agent and a script." |
| **5:30–6:15** | Break Google Sheets, re-run | "Excel still succeeds. Sheets fails with the actual cause and a fix. Verification degrades to PARTIAL rather than claiming success. One broken integration doesn't take down the run." |
| **6:15–6:45** | Unset the API key, re-run | "Exit 2. No silent downgrade — if the model can't choose the tools, the agent refuses rather than quietly running a fixed sequence and reporting the same success." |
| **6:45–7:00** | *(optional)* `tests/test_gemini_provider.py`, the signature tests | "The live run caught something unit tests couldn't: Gemini 3 requires an opaque reasoning token echoed back on every tool call. Four regression tests now pin it." |
| **6:45–7:15** | `logs/agent.jsonl`, then `pytest -q` | "Structured JSON logs, one object per line, tagged with a run id. 101 tests — no network, no API key, no Excel required." |
| **7:15–7:45** | `config.yaml` → `enabled_tools`, `provider` | "Delete a tool from this list and the model never sees it. Switch `provider` to `gemini` and the same tools run through a different model — the adapter translates, the tool code doesn't change." |
| **7:45–8:00** | `claude mcp list` → `sheetagent ✔ Connected` | "The same four tools are also exposed over MCP, so Claude Code can drive the workflow directly instead of the CLI." |

---

## The exact commands

**1 — Headline run (1:20)**

```bash
python -m sheetagent "Create a sample employee CSV and import it into Excel and Google Sheets."
```

Verified output — all four steps green:

```
1. generate_employee_csv: SUCCESS
   Generated 20 employee rows at output\employees.csv
2. import_csv_to_excel: SUCCESS
   Saved workbook to ...\output\employees.xlsx using the com engine
3. import_csv_to_google_sheets: SUCCESS
   Wrote 20 rows to Google Sheet https://docs.google.com/spreadsheets/d/...
4. verify_imports: SUCCESS
   Both imports verified against the CSV.
```

**2 — Dynamic tool selection (4:50)**

```bash
python -m sheetagent "Just generate 25 employee records as a CSV. Don't open Excel or touch Google Sheets."
```

**3 — Graceful failure (5:30)**

```bash
ren credentials.json credentials.json.bak
python -m sheetagent "Create an employee CSV and import it into Excel and Google Sheets."
ren credentials.json.bak credentials.json
```

Excel succeeds, Sheets reports `credentials file not found`, verify goes PARTIAL.

**4 — No silent downgrade (6:15)**

```bash
set GEMINI_API_KEY=
python -m sheetagent "Create an employee CSV."
```

```
error: GEMINI_API_KEY is not set, so the agent cannot plan or choose tools.
Set the key, or pass --test-mode to run the fixed deterministic plan used by CI.
```

Then restore the key.

**5 — Logs and tests (6:45)**

```bash
python -c "import json;[print(json.loads(l)['msg']) for l in open('logs/agent.jsonl',encoding='utf-8')][:15]"
pytest -q
```

---

## Points worth making out loud

Reviewers are looking for judgment, not just working code. These land:

- **"Verification is a separate tool."** The agent cannot mark its own homework.
- **"Retries are classified, not blanket."** A missing credentials file fails on
  attempt 1; a `429` gets exponential backoff. Retrying a deterministic failure
  is theatre.
- **"It refuses to run without a key."** An agent whose premise is that a model
  chooses the tools must not degrade to a fixed sequence and report the same
  success.
- **"The container can't do Excel, and says so."** COM needs Windows, so the
  Docker image is scoped as a CI/test runner and every headless run reports
  `excel_launched: false`.

---

## Do not claim on camera

Accuracy matters more than polish; a reviewer who catches one overstatement
discounts everything else.

- **Don't say the Docker image runs the full agent.** It cannot launch Excel.
- **Don't say the Anthropic path is verified.** The Anthropic provider is
  implemented and unit-tested, but no live Anthropic run has been made. The
  demo runs on **Gemini**, which *is* live-verified end to end.
- **Don't say the service account creates the sheet.** It cannot — it has no
  Drive storage. It writes to a sheet you created and shared with it. If asked
  why, that's a good answer to have ready: it's a real Google constraint that
  the README now documents.

---

## If something breaks mid-recording

| Symptom | Fix |
|---|---|
| Excel step fails, sharing violation | A stray `EXCEL.EXE` holds the workbook. Kill it in Task Manager. |
| Sheets step 403 | `sheets.spreadsheet_id` is blank or the share lapsed. Re-share with the service-account address. |
| `CONNECTION_CLOSED` from MCP | Registration points at a bare `python`. Re-register with the absolute `.venv` interpreter path. |
| Agent exits 2 immediately | The provider's key (`GEMINI_API_KEY`) isn't set in *this* shell. |
