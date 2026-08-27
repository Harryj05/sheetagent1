# SheetAgent

An autonomous AI agent that takes one natural-language instruction and does the
whole job: generates realistic employee data, launches **Microsoft Excel**,
imports and saves the workbook, pushes the same data into **Google Sheets** via
the Sheets API, verifies both, and reports what happened.

```
python -m sheetagent "Create a sample employee CSV and import it into Excel and Google Sheets."
```

No further interaction is required after that command.

---

## How it works, in plain words

**1.** You type one sentence, like *"Create an employee CSV and import it into
Excel and Google Sheets."*

**2.** The agent has four tools it can use: make a CSV, put data into Excel, put
data into Google Sheets, and check that both worked.

**3.** It does **not** follow a fixed list of steps. It sends your sentence to an
AI model along with a list of what tools exist.

**4.** The model first makes a **plan** — "I will do this, then this, then this."
The plan is printed for you before anything runs.

**5.** If the model names a tool that does not exist, that step is thrown away.
It can only use real tools.

**6.** Then the work starts. The model says *"run this tool"*, the runtime runs
it, and the result goes back to the model.

**7.** The model reads the result and decides what to do next. This repeats until
the job is done.

**8.** If a tool fails, the model is told that it failed and why. The run
continues with the steps that still work instead of crashing.

**9.** The tools do the real work — Excel actually opens on your screen and saves
the file, and Google Sheets is filled through Google's official API.

**10.** At the end, a **separate** tool checks the work. It re-opens the saved
Excel file and re-reads the Google Sheet, then compares both against the original
CSV. The agent is not allowed to simply claim success — it has to prove it.

**11.** If something fails for a permanent reason (a missing credentials file) it
does not retry, because retrying cannot help. If it fails for a temporary reason
(the API is busy) it waits and tries again.

**12.** Finally it prints a report showing which steps passed and which failed,
with file paths and the Google Sheet link.

### The key idea in one line

> A normal script is told **what steps to do**. This agent is told **what tools
> exist** — and it decides the steps itself.

That is why the same program handles *"just make a CSV"* (one tool) and *"do
everything"* (four tools) without changing a single line of code.

---

## How it works, in detail

```
natural language
       │
       ▼
┌──────────────┐   plan (JSON)   ┌───────────────────────────────┐
│   Planner    │ ───────────────►│  Executor: tool-calling loop  │
│ (the model)  │                 │  over the tool registry       │
└──────────────┘                 └───────────────┬───────────────┘
                                                 │ selects tools dynamically
        ┌────────────────────────────────────────┼────────────────────────┐
        ▼                    ▼                   ▼                        ▼
 generate_employee_csv  import_csv_to_excel  import_csv_to_google_sheets  verify_imports
                             │ COM / openpyxl        │ Sheets API v4          │ re-reads both
                             ▼                       ▼                        ▼
                        employees.xlsx        Google Spreadsheet        pass / fail report
```

The model is **Gemini by default, Anthropic optionally** — the same loop, the
same tools, either way.

Two stages, deliberately separated:

1. **Plan** — the model is asked for an ordered plan naming a tool per step and
   the risks it foresees. Unknown tool names are dropped before execution, so a
   hallucinated step can never run. The plan is printed and stored in memory.
2. **Execute** — a tool-calling loop. The model picks the tool and its
   arguments each turn; the runtime executes it, feeds the JSON result back
   (with `is_error` set on failures) and lets the model adapt. Nothing about the
   step order is hardcoded into a script — swap the prompt and a different
   subset of tools runs.

Every tool is a plain Python function registered with `@tool(...)`; the registry
turns it into a tool schema, executes it defensively (a raising tool becomes a
structured `{"status": "failed", ...}` result, never a crash) and emits progress
events. The registry's schema format is Anthropic-shaped and is the single
source of truth — the Gemini adapter translates *from* it, so adding a provider
never means touching a tool.

### Design decisions worth knowing

| Decision | Why |
|---|---|
| Excel via **COM (pywin32)** with an **openpyxl fallback** | The assignment asks for the real Excel application. COM does that on Windows. Everywhere else the agent still completes headlessly and *says so* in its result (`engine`, `fallback_reason`, `warning`) instead of quietly pretending. Setting `excel.engine: com` disables the fallback and fails loudly. |
| Independent `verify_imports` tool | The agent isn't allowed to claim success from its own earlier output. Verification re-opens the saved workbook and re-reads the live Google Sheet, then compares headers and row counts against the CSV. |
| Memory replays a fixed window, not the whole transcript | Facts (last CSV path, last spreadsheet URL) are kept forever because they are tiny and are what makes a follow-up run useful. The transcript is capped two ways: `tool_result` blocks are stored as `status` + `summary` only, and just the last two exchanges are replayed. Run 50's prompt is the same size as run 1's. |
| Providers are adapters, not branches | `agent.py` and `planner.py` know exactly one interface — `client.messages.create(...) -> response.content`. Gemini support is a translation layer (`sheetagent/providers/gemini.py`) that reshapes tool schemas, conversation and responses into that interface. The tool registry stays the single source of truth: switching provider changes no tool code and no executor code. |
| Model calls retry, tool calls retry, both by error class | A 503 or 429 from the provider is transient and is retried with backoff; a 400 is not. Without this a single load spike ends a run that has already opened Excel and written a spreadsheet. |
| `give_up_on` in the retry helper | Retrying a missing credentials file three times is theatre. Configuration errors fail on attempt 1; transient API errors get exponential backoff. |
| **No silent downgrade** | Without a key for the configured provider (`GEMINI_API_KEY` by default) the agent refuses to start (exit 2). An agent whose premise is "the model chooses the tools" must not quietly run a fixed sequence and report the same success. |
| `--test-mode` lives in `tests/` | CI still needs to exercise the tool layer, retries and verification without a key. That fixed plan is a **test double**, kept in `tests/support/deterministic_planner.py` so it can never be mistaken for the product's planner, and every plan it produces is labelled `DETERMINISTIC TEST PLANNER`. |

---

## Setup

### 1. Install

```bash
git clone <your-repo> sheetagent && cd sheetagent
python -m venv .venv
# Windows:  .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

`pywin32` installs only on Windows (marker-gated in `requirements.txt`).

### 2. Model API key

The default provider is **Gemini**. See [Model providers](#model-providers) to
use Anthropic instead.

```bash
cp .env.example .env      # then edit
export GEMINI_API_KEY=...                  # Windows: setx GEMINI_API_KEY ...
```

The agent will not start without a key for the configured provider — that is
deliberate, not a bug. See the no-silent-downgrade note below.

### 3. Microsoft Excel

Nothing to configure — Excel must simply be installed. Verify COM works:

```bash
python -c "import win32com.client as w; print(w.Dispatch('Excel.Application').Version)"
```

### 4. Google Sheets

Either auth style works; the tool detects which one you gave it.

**Service account**

> **A service account has no Drive storage of its own and cannot create files.**
> `spreadsheets.create` fails with a bare `403 The caller does not have
> permission`; the underlying cause is `The user's Drive storage quota has been
> exceeded`. Leaving `sheets.spreadsheet_id` blank therefore *cannot* work with
> a service account - it must be pointed at a sheet that already exists.

1. Google Cloud Console -> new project -> enable **Google Sheets API** and
   **Google Drive API**.
2. *IAM & Admin -> Service Accounts* -> create one -> *Keys* -> add key -> JSON.
3. Save it as `credentials.json` in the project root (gitignored).
4. Create a blank sheet at <https://sheets.new>, **Share** it with the
   service-account address (`...iam.gserviceaccount.com`) as **Editor**, and copy
   the id from the URL:
   `https://docs.google.com/spreadsheets/d/<THIS>/edit`
5. Put that id in `config.yaml` under `sheets.spreadsheet_id`.

Google warns that the address is not a Google account and will not be notified.
That is expected - click through it.

**OAuth desktop client (lets the agent create sheets itself)**

1. Same project -> *APIs & Services -> Credentials* -> OAuth client ID ->
   *Desktop app*.
2. Download as `credentials.json`. The tool detects which shape it was given.
3. Leave `sheets.spreadsheet_id` blank; each run creates a new spreadsheet in
   **your** Drive, so the storage-quota limit does not apply.

First run opens a browser once and caches the grant in `token.json`; later runs
are unattended.

---

## Usage

```bash
# the headline command
python -m sheetagent "Create a sample employee CSV and import it into Excel and Google Sheets."

# partial workflows - the agent picks the tools, not a script
python -m sheetagent "Just generate 50 employee records as a CSV, nothing else."
python -m sheetagent "Make employee data and put it in Excel only. Skip Google Sheets."
python -m sheetagent "Generate 30 employees, save as .ods, and upload to Google Sheets."

# reuse an existing spreadsheet
python -m sheetagent "Refresh spreadsheet 1AbC...xyz with 40 new employee rows."

# machine-readable result, engine override
python -m sheetagent --json "...">result.json
python -m sheetagent --excel-engine openpyxl "..."

# CI / offline testing only - NOT a supported way to run the agent.
# Replaces the model planner with a fixed plan that does no reasoning.
python -m sheetagent --test-mode "Create an employee CSV and import it into Excel."
```

Flags: `--config`, `--rows N`, `--json`, `--quiet`, `--log-level`,
`--excel-engine {auto,com,openpyxl}`, `--test-mode`.

A key for the configured provider is **required** — `GEMINI_API_KEY` by
default. Without it the agent exits 2 rather than degrading to a non-reasoning
plan.

`EXAMPLE_PROMPTS.md` has the full list with what each one should produce.

### MCP server

The same tools are exposed over MCP, so Claude Desktop or Claude Code can drive
the workflow instead of the CLI:

```bash
python -m sheetagent.mcp_server
```

`claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "sheetagent": {
      "command": "/absolute/path/to/sheetagent/.venv/bin/python",
      "args": ["-m", "sheetagent.mcp_server"],
      "cwd": "/absolute/path/to/sheetagent"
    }
  }
}
```

Or register it with Claude Code directly. **Use an absolute path to the
virtualenv interpreter** — MCP servers are launched by the client, not from your
shell, so a bare `python` resolves against the client's PATH and will usually be
a global interpreter that lacks this project's dependencies. The failure mode is
`CONNECTION_CLOSED` with no further explanation.

```bash
# Windows
claude mcp add sheetagent -- C:\path\to\sheetagent\.venv\Scripts\python.exe -m sheetagent.mcp_server

# macOS / Linux
claude mcp add sheetagent -- /path/to/sheetagent/.venv/bin/python -m sheetagent.mcp_server
```

Verify with `claude mcp list`; a healthy registration reports `✔ Connected`.

The server supports both `mcp` 1.x (`FastMCP`) and 2.x (`MCPServer`), and each
tool's MCP input schema is derived from the same registry schema the
tool-calling loop uses, so the two surfaces cannot drift apart.

---

## Docker — CI / headless test runner

**This image is not a deployment of the full agent.** The Excel requirement
means launching the real Microsoft Excel application, which SheetAgent does via
COM (pywin32) — that needs Windows and an installed Excel. A Linux container has
neither, and `pywin32` is marker-gated so it is not installed in the image at
all.

| | In the container | Native on Windows |
|---|---|---|
| Launch Microsoft Excel | **No** | Yes |
| COM engine + its error classification | **No** | Yes |
| Planner, tool-calling loop, tool selection | Yes | Yes |
| CSV generation | Yes | Yes |
| Workbook written (headless, openpyxl) | Yes | Yes |
| Google Sheets import | Yes | Yes |
| Verification, MCP server | Yes | Yes |
| Test suite | Yes | Yes |

Use the image to run the suite reproducibly and to exercise everything that is
not COM. **Run natively on Windows for the demo and for anything meant to
satisfy the Excel requirement.**

```bash
docker build -t sheetagent .

# what the image is for: the test suite
docker run --rm sheetagent

# exercise the workflow headlessly (openpyxl, no Excel)
docker run --rm -v "$PWD/output:/app/output"   sheetagent python -m sheetagent --test-mode   "Create an employee CSV and import it into Excel."

# with a key and credentials, the model-driven path minus Excel (Gemini by default)
docker run --rm   -e GEMINI_API_KEY   -v "$PWD/credentials.json:/app/credentials.json:ro"   -v "$PWD/output:/app/output"   -v "$PWD/logs:/app/logs"   sheetagent python -m sheetagent "Generate 30 employees and upload them to Google Sheets."
```

The image pins `SHEETAGENT_EXCEL_ENGINE=openpyxl` rather than relying on `auto`,
so a container run never even appears to have attempted COM. Every headless run
reports `"excel_launched": false` plus an explicit warning naming the engine
that actually wrote the workbook, so a container run cannot be mistaken for one
that drove Excel:

```json
{
  "status": "success",
  "engine": "openpyxl",
  "excel_launched": false,
  "warning": "Microsoft Excel was NOT launched; the workbook was written headlessly by the openpyxl engine. Run natively on Windows with excel.engine=auto or com to drive the real application."
}
```

`output/`, `logs/` and `memory/` are volumes so artifacts outlive the container.
The image runs as a non-root user.

---

## Model providers

Set `agent.provider` in `config.yaml` (or `SHEETAGENT_PROVIDER`):

| Provider | Key | Model | Status |
|---|---|---|---|
| `gemini` (default) | `GEMINI_API_KEY` | `gemini-3.1-flash-lite` | Verified end to end against the live API |
| `anthropic` | `ANTHROPIC_API_KEY` | `claude-sonnet-5` | Implemented and unit-tested; no live run made |

Gemini is the default because it is the path that has actually been run against
a live API, tools and all. Switching is a two-line config change.

```yaml
agent:
  provider: anthropic       # the non-default
  model: claude-sonnet-5
```

```bash
# default - nothing to change
export GEMINI_API_KEY=...
python -m sheetagent "Create an employee CSV and import it into Excel and Google Sheets."

# or switch to Anthropic
export ANTHROPIC_API_KEY=sk-ant-...
python -m sheetagent --config config.yaml "..."      # with provider: anthropic set
```

The agent loop is provider-agnostic. `sheetagent/providers/gemini.py` performs
three translations and nothing else:

1. registry `input_schema` → Gemini `functionDeclarations` (dropping schema keys
   Gemini's parser rejects, such as `default` and `additionalProperties`);
2. Anthropic `messages` → Gemini `contents`, mapping `tool_use`/`tool_result`
   onto `functionCall`/`functionResponse`;
3. Gemini parts → blocks exposing `.type`, `.text`, `.name`, `.input`, `.id`.

Gemini has no tool-call id and keys its `functionResponse` by function *name*,
so the adapter synthesises `"<name>::<n>"` — the name is recoverable from the id
without holding cross-call state.

`google-genai` ships in `requirements.txt` since Gemini is the default; it is
still imported lazily, so an Anthropic-only deployment can drop it.

**Verified against the live Gemini API.** Gemini 3.x attaches an opaque
`thought_signature` to every `functionCall` part and rejects the following turn
with `400 INVALID_ARGUMENT` unless it is echoed back verbatim. The adapter
carries it on the tool-use block so the executor replays history unchanged
without knowing this provider detail exists.

---

## Configuration

Everything lives in `config.yaml`; environment variables override it
(`SHEETAGENT_MODEL`, `SHEETAGENT_EXCEL_ENGINE`, `SHEETAGENT_SPREADSHEET_ID`,
`GOOGLE_CREDENTIALS_FILE`, `SHEETAGENT_LOG_LEVEL`). Removing a name from
`agent.enabled_tools` hides that tool from the model entirely — that is how you
turn the agent into a CSV-only or Excel-only agent without touching code.

## Output

```
output/employees.csv     generated data (20+ rows)
output/employees.xlsx    saved workbook (formatted table, frozen header)
logs/agent.jsonl         one JSON object per log line, tagged with a run_id
memory/conversation.json facts from previous runs + a capped transcript
```

Inspect a run: `jq 'select(.event=="step_failed")' logs/agent.jsonl`

## Tests

```bash
pip install -r requirements-dev.txt
pytest -q                       # 73 tests, no network, no API key
pytest --cov=sheetagent -q
```

Both model clients and the Google API client are stubbed, so the planner,
the tool-calling loop, failure propagation, retry semantics and verification are
all covered offline.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `pywin32 is not installed / not on Windows` | Expected off Windows — the openpyxl fallback runs. On Windows: `pip install pywin32` then `python Scripts/pywin32_postinstall.py -install`. |
| `credentials file not found` | Step 4 above; check `sheets.credentials_file`. |
| `503 UNAVAILABLE` / `429` from the model | Retried automatically with backoff, so most spikes are invisible. If every attempt fails, that model is genuinely saturated - switch `agent.model` (each model has its own quota and load). |
| `429 RESOURCE_EXHAUSTED` from Gemini | The free tier allows 20 requests per day *per model*, and one agent run costs several. Switch `agent.model` to another model (`gemini-3.6-flash`, `gemini-3.5-flash-lite`) — each has its own quota — or wait for the reset. |
| Run stops with `the model provider returned an error` | Expected behaviour, not a crash: a provider outage or rate limit ends the run cleanly and the report lists whatever completed first. Re-run when the provider recovers. |
| `403 The caller does not have permission` when creating a sheet | A service account cannot create Drive files at all. Create the sheet yourself, share it with the service-account address as Editor, and set `sheets.spreadsheet_id`. |
| `403 Google Sheets API has not been used` | Enable the Sheets **and** Drive APIs in the Cloud project. |
| Excel opens but the workbook doesn't save | Close any modal dialog in Excel; the agent sets `DisplayAlerts = False` but a pre-existing dialog blocks COM. |
| Agent stops after `max_iterations` | Raise `agent.max_iterations` in `config.yaml`. |

## Project layout

```
sheetagent/
  agent.py          plan → tool-calling loop → report
  planner.py        structured planning (model-driven; no fallback path)
  registry.py       @tool decorator, schemas, defensive execution
  events.py         progress events (CLI subscribes, MCP forwards)
  memory.py         cross-run facts (kept) + bounded transcript replay
  retry.py          exponential backoff with unrecoverable-error short circuit
tests/support/      deterministic_planner.py - the --test-mode test double
  config.py         YAML + env configuration
  logging_setup.py  structured JSON logging
  providers/        anthropic | gemini clients behind one interface
  cli.py            command-line entrypoint
  mcp_server.py     the same tools over MCP (schemas derived from the registry)
  tools/
    csv_tool.py     generate_employee_csv
    excel_tool.py   import_csv_to_excel   (COM | openpyxl | odfpy)
    sheets_tool.py  import_csv_to_google_sheets
    verify_tool.py  verify_imports
tests/              73 unit + integration tests
```
