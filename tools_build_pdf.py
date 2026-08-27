"""Build the submission PDF: how the agent works + interactive prompts."""
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (BaseDocTemplate, Frame, HRFlowable, KeepTogether,
                                PageBreak, PageTemplate, Paragraph, Spacer, Table,
                                TableStyle)

OUT = r"C:\Users\saura\Claude\Projects\sheetagent\sheetagent\SheetAgent-Submission.pdf"

INK = colors.HexColor("#101A1D")
MUTED = colors.HexColor("#5C6E73")
ACCENT = colors.HexColor("#1F5F7A")
OK = colors.HexColor("#1F7A5E")
WARN = colors.HexColor("#A8412C")
RULE = colors.HexColor("#D3DBDD")
CODEBG = colors.HexColor("#F2F5F6")

ss = getSampleStyleSheet()


def S(name, **kw):
    base = kw.pop("parent", ss["Normal"])
    return ParagraphStyle(name, parent=base, **kw)


TITLE = S("t", fontName="Helvetica-Bold", fontSize=23, leading=27, textColor=INK,
          spaceAfter=3)
SUB = S("s", fontSize=11.5, leading=15, textColor=MUTED, spaceAfter=14)
H1 = S("h1", fontName="Helvetica-Bold", fontSize=14.5, leading=18, textColor=INK,
       spaceBefore=16, spaceAfter=7)
H2 = S("h2", fontName="Helvetica-Bold", fontSize=11, leading=14, textColor=ACCENT,
       spaceBefore=11, spaceAfter=4)
BODY = S("b", fontSize=9.9, leading=14.2, textColor=INK, alignment=TA_LEFT,
         spaceAfter=6)
SMALL = S("sm", fontSize=8.8, leading=12.4, textColor=MUTED, spaceAfter=5)
BULLET = S("bu", parent=BODY, leftIndent=13, bulletIndent=3, spaceAfter=3.5)
CODE = S("c", fontName="Courier", fontSize=8.6, leading=11.6, textColor=INK,
         backColor=CODEBG, borderPadding=(6, 7, 6, 7), spaceBefore=3, spaceAfter=7,
         leftIndent=1)
CELL = S("cell", fontSize=8.9, leading=12, textColor=INK)
CELLH = S("cellh", fontSize=8.6, leading=11, textColor=MUTED,
          fontName="Helvetica-Bold")


def rule(space_before=3, space_after=8):
    return HRFlowable(width="100%", thickness=0.6, color=RULE,
                      spaceBefore=space_before, spaceAfter=space_after)


def table(rows, widths, header=True):
    data = [[Paragraph(c, CELLH if (header and r == 0) else CELL) for c in row]
            for r, row in enumerate(rows)]
    t = Table(data, colWidths=widths, hAlign="LEFT")
    style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, RULE),
    ]
    if header:
        style += [("LINEBELOW", (0, 0), (-1, 0), 0.9, MUTED)]
    t.setStyle(TableStyle(style))
    return t


def prompt_block(n, title, prompt, outcome, verified=False):
    tag = ' <font color="#1F7A5E"><b>[verified live]</b></font>' if verified else ""
    parts = [Paragraph(f"{n}. {title}{tag}", H2),
             Paragraph(prompt.replace("&", "&amp;"), CODE),
             Paragraph(outcome, BODY)]
    return KeepTogether(parts)


def footer(canvas, doc):
    canvas.saveState()
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.5)
    canvas.line(20 * mm, 15 * mm, A4[0] - 20 * mm, 15 * mm)
    canvas.setFont("Helvetica", 7.6)
    canvas.setFillColor(MUTED)
    canvas.drawString(20 * mm, 10.5 * mm, "SheetAgent - autonomous spreadsheet agent")
    canvas.drawRightString(A4[0] - 20 * mm, 10.5 * mm, f"Page {doc.page}")
    canvas.restoreState()


story = []
A = story.append

A(Paragraph("SheetAgent", TITLE))
A(Paragraph("An autonomous AI agent that takes one natural-language instruction and "
            "generates employee data, drives Microsoft Excel, writes the same data to "
            "Google Sheets, verifies both, and reports what happened.", SUB))
A(rule(0, 10))

A(Paragraph("Submitted by", H2))
A(table([
    ["Repository", "github.com/Harryj05/sheetagent1"],
    ["Model provider", "Gemini (gemini-3.6-flash) by default; Anthropic supported"],
    ["Tests", "102 passing - no network, no API key, no Excel required"],
    ["Platform", "Windows for the real-Excel path; Linux/CI runs headless"],
], [32 * mm, 128 * mm], header=False))

A(Paragraph("How the agent works", H1))
A(Paragraph("A normal script is told <b>what steps to do</b>. This agent is told "
            "<b>what tools exist</b> and decides the steps itself. That is why the same "
            "program handles \"just make a CSV\" (one tool) and \"do everything\" "
            "(four tools) without a line of code changing.", BODY))

steps = [
    "You type one sentence. The agent has four tools: make a CSV, import into Excel, "
    "import into Google Sheets, and verify both.",
    "The request and the tool catalogue go to the model. The model returns an ordered "
    "<b>plan</b>, which is printed before anything runs.",
    "Any step naming a tool that does not exist is discarded, so a hallucinated step "
    "can never execute.",
    "The executor loop begins: the model asks for a tool, the runtime runs it, and the "
    "result goes back to the model, which decides what to do next.",
    "If a tool fails, the model is told it failed and why. The run continues with the "
    "steps that still work rather than crashing.",
    "The tools do real work - Excel actually opens and saves the workbook; Google "
    "Sheets is written through the official Sheets API v4.",
    "A <b>separate</b> tool then verifies: it re-opens the saved workbook and re-reads "
    "the live sheet, comparing both against the source CSV. The agent may not simply "
    "claim success.",
    "Permanent failures (missing credentials) are not retried; transient ones (rate "
    "limits, Excel busy) get exponential backoff.",
    "A final report lists every step as SUCCESS, FAILED or PARTIAL, with file paths "
    "and the spreadsheet URL.",
]
for i, text in enumerate(steps, start=1):
    A(Paragraph(text, BULLET, bulletText=f"{i}."))

A(PageBreak())

A(Paragraph("Interactive prompts", H1))
A(Paragraph("Run any of these with <font face='Courier'>python -m sheetagent "
            "\"&lt;prompt&gt;\"</font>. Nothing else is required after the command. "
            "Prompts marked <b>[verified live]</b> have been executed end to end "
            "against the real Excel application and the live Google Sheets API.", BODY))

A(prompt_block(
    1, "The assignment prompt - full workflow",
    "Create a sample employee CSV and import it into Excel and Google Sheets.",
    "All four tools run: generate, Excel, Sheets, verify. In the recorded run the model "
    "planned four steps, chose 25 rows on its own initiative, drove Excel through COM, "
    "wrote 25 rows to the live sheet, and verification confirmed the row count and all "
    "nine headers (<font face='Courier'>all_verified: true</font>).", verified=True))

A(prompt_block(
    2, "Explicit row count",
    "Generate 50 realistic employee records, import them into Excel, upload them to\n"
    "Google Sheets, and confirm both imports succeeded.",
    "Demonstrates that quantities are taken from the request, not from a constant."))

A(prompt_block(
    3, "CSV only - proves tool selection is dynamic",
    "Just generate 25 employee records as a CSV file. Don't open Excel or touch\n"
    "Google Sheets.",
    "One tool call instead of four. Same code, same registry - the model read the "
    "request and chose. This is the clearest evidence the workflow is not hardcoded."))

A(prompt_block(
    4, "Excel only",
    "Make some employee data and get it into Excel. Skip Google Sheets entirely.",
    "Two tools. The Google Sheets tool is never invoked."))

A(prompt_block(
    5, "Alternate spreadsheet format",
    "Create 30 employee records, save the workbook as an .ods file, and also upload\n"
    "the data to Google Sheets.",
    "Exercises the XLSX / XLSM / CSV / ODS support in the Excel tool."))

A(prompt_block(
    6, "Write into an existing spreadsheet",
    "Regenerate the employee data with 40 rows and write it into the existing\n"
    "spreadsheet 1AbCdEfGhIjKlMnOpQrStUvWxYz.",
    "Overrides the configured spreadsheet id for a single run."))

A(prompt_block(
    7, "Memory across runs",
    "Run 1:  Create an employee CSV and import it into Excel.\n"
    "Run 2:  Now upload the CSV you made last time to Google Sheets.",
    "The second run resolves the path from persisted memory rather than asking."))

A(prompt_block(
    8, "Error handling, on purpose",
    "Import /tmp/definitely-not-here.csv into Excel and Google Sheets.",
    "The tool returns <font face='Courier'>status: failed</font> with the reason and a "
    "hint; the agent reports the failure rather than inventing success. Verified live: "
    "the report read <i>import_csv_to_excel: FAILED - CSV not found</i>.",
    verified=True))

A(prompt_block(
    9, "Verification only",
    "Check whether output/employees.xlsx and the Google Sheet still match\n"
    "output/employees.csv.",
    "A single tool call that re-reads both targets and compares them to the CSV."))

A(PageBreak())

A(Paragraph("Requirements coverage", H1))
A(Paragraph("Functional requirements", H2))
A(table([
    ["Requirement", "Status"],
    ["Accept natural language input", "Met"],
    ["Decide which tools to execute", "Met - model-driven, verified live"],
    ["Generate a CSV automatically", "Met"],
    ["At least 20 rows of realistic data", "Met - 20+ rows, 9 columns"],
    ["Launch Microsoft Excel", "Met - real COM, Excel 16.0"],
    ["Import the CSV into Excel", "Met"],
    ["Save the workbook", "Met - frozen header, numeric salaries"],
    ["Connect via the Google Sheets API", "Met - Sheets API v4, verified live"],
    ["Import the same CSV into a Google Sheet", "Met"],
    ["Report whether each step succeeded", "Met"],
    ["Handle errors gracefully", "Met"],
], [95 * mm, 65 * mm]))

A(Paragraph("Bonus items", H2))
A(table([
    ["Item", "Notes"],
    ["Multi-step planning", "Separate planner stage; unknown tools dropped"],
    ["Memory / conversation history", "Facts kept; transcript bounded to a constant"],
    ["XLSX / CSV / ODS", "Plus XLSM"],
    ["Retry logic", "Classified per error class in both integrations"],
    ["Configurable tools", "enabled_tools hides a tool from the model entirely"],
    ["MCP server", "Four tools exposed; schemas derived from the registry"],
    ["Dockerized deployment", "Builds; scoped honestly as a CI / headless runner"],
    ["Unit tests", "102, fully offline"],
    ["Structured logging", "JSONL, one object per line, run-id tagged"],
    ["Progress updates", "Live event feed during execution"],
], [55 * mm, 105 * mm]))

A(Paragraph("Beyond the brief: a second model provider (Gemini) behind an adapter, and "
            "GitHub Actions CI running the suite on Ubuntu with no Excel and no "
            "credentials present.", SMALL))

A(Paragraph("Quick start", H1))
A(Paragraph(
    "python -m venv .venv<br/>"
    ".venv\\Scripts\\python.exe -m pip install -r requirements.txt<br/>"
    "set GEMINI_API_KEY=your-key<br/>"
    "python -m sheetagent \"Create a sample employee CSV and import it into Excel "
    "and Google Sheets.\"", CODE))
A(Paragraph("Full setup, including both Google authentication flows, is in the "
            "repository README.", SMALL))

A(Paragraph("Two limitations worth stating plainly", H1))
A(Paragraph(
    "<b>A Google service account cannot create spreadsheets.</b> It has no Drive "
    "storage quota, so it must be pointed at a sheet you created and shared with it. "
    "With OAuth desktop credentials the agent creates sheets itself. The README "
    "documents both.", BODY))
A(Paragraph(
    "<b>The Docker image cannot launch Excel.</b> COM requires Windows and an installed "
    "Excel, so the image is scoped as a CI and headless test runner. Every headless run "
    "reports <font face='Courier'>excel_launched: false</font> rather than implying "
    "Excel ran.", BODY))

doc = BaseDocTemplate(OUT, pagesize=A4, title="SheetAgent - Submission",
                      author="Harshit Jain", leftMargin=20 * mm, rightMargin=20 * mm,
                      topMargin=18 * mm, bottomMargin=20 * mm)
frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="f")
doc.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=footer)])
doc.build(story)
print("built:", OUT)
