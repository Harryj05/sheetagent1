import csv
from pathlib import Path

import pytest

from sheetagent.tools.csv_tool import ALL_COLUMNS, BASE_COLUMNS, build_rows, generate_employee_csv


def test_build_rows_minimum_twenty():
    rows = build_rows(20, seed=1)
    assert len(rows) == 20
    assert all(set(BASE_COLUMNS) <= set(r) for r in rows)


def test_employee_ids_sequential_and_unique():
    rows = build_rows(35, seed=7)
    ids = [r["Employee ID"] for r in rows]
    assert ids[0] == "EMP001" and ids[-1] == "EMP035"
    assert len(set(ids)) == len(ids)


def test_emails_unique_and_wellformed():
    rows = build_rows(60, seed=3)
    emails = [r["Employee ID"] and r["Email"] for r in rows]
    assert len(set(emails)) == len(emails)
    assert all("@" in e and e.endswith("example.com") for e in emails)


def test_salaries_are_positive_ints():
    for row in build_rows(30, seed=11):
        assert isinstance(row["Salary"], int) and row["Salary"] > 0


def test_seed_is_deterministic():
    assert build_rows(10, seed=42) == build_rows(10, seed=42)


def test_rejects_zero_rows():
    with pytest.raises(ValueError):
        build_rows(0)


def test_tool_writes_file_and_sets_state(ctx):
    result = generate_employee_csv(ctx=ctx, row_count=20, seed=5)
    assert result["status"] == "success"
    path = Path(result["csv_path"])
    assert path.exists()
    with path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    assert rows[0] == ALL_COLUMNS
    assert len(rows) == 21          # header + 20
    assert ctx.state["csv_path"] == str(path)


def test_base_columns_only(ctx):
    result = generate_employee_csv(ctx=ctx, row_count=5, extra_columns=False,
                                   filename="small.csv")
    assert result["columns"] == BASE_COLUMNS
