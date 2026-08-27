# Example prompts

The point of these is that **no step order is hardcoded** — the agent reads the
request, plans, and calls only the tools it needs.

### 1. The assignment prompt (full workflow)
```
Create a sample employee CSV and import it into Excel and Google Sheets.
```
→ all four tools: generate → Excel → Sheets → verify.

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
spreadsheet 1AbCdEfGhIjKlMnOpQrStUvWxYz instead of creating a new one.
```

### 7. Memory across runs
```
Run 1: Create an employee CSV and import it into Excel.
Run 2: Now upload the CSV you made last time to Google Sheets.
```
→ run 2 resolves the path from `memory/conversation.json`.

### 8. Error handling on purpose
```
Import /tmp/definitely-not-here.csv into Excel and Google Sheets.
```
→ both tools return `status: failed` with a hint; the agent reports the failure
rather than inventing success.

### 9. Verification only
```
Check whether output/employees.xlsx and the Google Sheet still match output/employees.csv.
```
