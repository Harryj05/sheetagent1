"""Tool: generate a realistic employee CSV."""
from __future__ import annotations

import csv
import logging
import random
import unicodedata
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from ..registry import ToolContext, tool
from .data import DEPARTMENTS, FIRST_NAMES, LAST_NAMES, LOCATIONS

log = logging.getLogger("sheetagent.tools.csv")

BASE_COLUMNS = ["Employee ID", "Name", "Department", "Email", "Salary"]
EXTRA_COLUMNS = ["Job Title", "Location", "Hire Date", "Manager"]
ALL_COLUMNS = BASE_COLUMNS + EXTRA_COLUMNS


def _slug(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return "".join(ch for ch in ascii_text.lower() if ch.isalnum() or ch == ".")


def build_rows(count: int, *, seed: int | None = None,
               extra_columns: bool = True,
               email_domain: str = "example.com") -> list[dict[str, Any]]:
    """Pure function - deterministic given a seed, which makes it testable."""
    if count < 1:
        raise ValueError("row_count must be >= 1")
    rng = random.Random(seed)
    departments = list(DEPARTMENTS)
    used_emails: set[str] = set()
    rows: list[dict[str, Any]] = []

    # One manager per department, drawn from the first employees created there.
    managers: dict[str, str] = {}

    for i in range(1, count + 1):
        first, last = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
        name = f"{first} {last}"
        dept = departments[(i - 1) % len(departments)] if i <= len(departments) \
            else rng.choice(departments)
        titles, (low, high) = DEPARTMENTS[dept]
        title = rng.choice(titles)
        salary = int(round(rng.uniform(low, high), -2))

        local = f"{_slug(first)}.{_slug(last)}"
        candidate, n = local, 1
        while candidate in used_emails:
            n += 1
            candidate = f"{local}{n}"
        used_emails.add(candidate)

        hire = date.today() - timedelta(days=rng.randint(30, 3650))
        row = {
            "Employee ID": f"EMP{i:03d}",
            "Name": name,
            "Department": dept,
            "Email": f"{candidate}@{email_domain}",
            "Salary": salary,
        }
        if extra_columns:
            row |= {
                "Job Title": title,
                "Location": rng.choice(LOCATIONS),
                "Hire Date": hire.isoformat(),
                "Manager": managers.get(dept, ""),
            }
        managers.setdefault(dept, name)
        rows.append(row)

    if extra_columns:  # backfill the first hire of each department
        for row in rows:
            if not row["Manager"]:
                row["Manager"] = "—"
    return rows


@tool(
    name="generate_employee_csv",
    description=(
        "Generate a CSV file of realistic sample employee records and write it to "
        "disk. Columns: Employee ID, Name, Department, Email, Salary, plus "
        "Job Title, Location, Hire Date and Manager when extra_columns is true. "
        "Call this first; every later step consumes the csv_path it returns."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "row_count": {"type": "integer", "minimum": 1, "maximum": 5000,
                          "default": 20,
                          "description": "Number of employee rows (assignment minimum: 20)."},
            "filename": {"type": "string",
                         "description": "Optional output filename, e.g. employees.csv."},
            "extra_columns": {"type": "boolean", "default": True,
                              "description": "Include Job Title / Location / Hire Date / Manager."},
            "seed": {"type": "integer",
                     "description": "Seed for reproducible sample data."},
        },
        "required": ["row_count"],
    },
)
def generate_employee_csv(ctx: ToolContext, row_count: int = 20,
                          filename: str | None = None,
                          extra_columns: bool = True,
                          seed: int | None = None) -> dict[str, Any]:
    out_dir = Path(ctx.config.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / (filename or "employees.csv")

    rows = build_rows(row_count, seed=seed, extra_columns=extra_columns)
    columns = ALL_COLUMNS if extra_columns else BASE_COLUMNS

    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)

    ctx.state["csv_path"] = str(path.resolve())
    ctx.state["csv_row_count"] = len(rows)
    ctx.state["csv_columns"] = columns
    log.info("wrote CSV", extra={"path": str(path), "rows": len(rows)})

    return {
        "status": "success",
        "csv_path": str(path.resolve()),
        "row_count": len(rows),
        "columns": columns,
        "preview": rows[:3],
        "summary": f"Generated {len(rows)} employee rows at {path}",
    }
