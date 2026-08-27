# Example prompts

The point of these is that **no step order is hardcoded** — the agent reads the
request, plans, and calls only the tools it needs.

Run them with `python -m sheetagent "<prompt>"`. Prompts marked **[verified]**
have been run end to end against the live APIs on Gemini.

> **Note on Google Sheets:** a service account cannot create spreadsheets, so
> `sheets.spreadsheet_id` must point at a sheet you created and shared with it.
> With OAuth desktop credentials the agent creates sheets itself. See the README.

### 1. The assignment prompt (full workflow) — **[verified]**
```
Create a sample employee CSV and import it into Excel and Google Sheets.
```
→ all four tools: generate → Excel → Sheets → verify.

Actual result: the model planned four steps, chose 25 rows on its own, drove
Excel through COM, wrote 25 rows to the live sheet, and verification confirmed
row counts and all 9 headers (`all_verified: true`).

### 2. Explicit row count
```
Generate 50 realistic employee records, import them into Excel, upload them to
Google Sheets, and confirm both imports succeeded.
```

### 3. CSV only — proves tool selection is dynamic
```
Just generate 25 employee records as a CSV file. Don't open Excel or touch Google Sheets.
```
→ one tool call.

### 4. Excel only
```
Make some employee data and get it into Excel. Skip Google Sheets entirely.
```

### 5. Alternate format (bonus: XLSX / CSV / ODS)
```
Create 30 employee records, save the workbook as an .ods file, and also upload
the data to Google Sheets.
```

### 6. Existing spreadsheet
```
Regenerate the employee data with 40 rows and write it into the existing
spreadsheet 1AbCdEfGhIjKlMnOpQrStUvWxYz.
```
→ overrides `sheets.spreadsheet_id` for this run. Replace the id with your own.

### 7. Memory across runs
```
Run 1: Create an employee CSV and import it into Excel.
Run 2: Now upload the CSV you made last time to Google Sheets.
```
→ run 2 resolves the path from `memory/conversation.json`.

### 8. Error handling on purpose — **[verified]**
```
Import /tmp/definitely-not-here.csv into Excel and Google Sheets.
```
→ both tools return `status: failed` with a hint; the agent reports the failure
rather than inventing success.

### 9. Verification only
```
Check whether output/employees.xlsx and the Google Sheet still match output/employees.csv.
```
