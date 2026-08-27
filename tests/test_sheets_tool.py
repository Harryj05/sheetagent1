import functools
from pathlib import Path

import httplib2
import pytest

from sheetagent.tools import sheets_tool
from sheetagent.tools.csv_tool import generate_employee_csv
from sheetagent.tools.sheets_tool import SheetsAuthError, import_csv_to_google_sheets
from sheetagent.tools.verify_tool import verify_imports


class FakeValues:
    def __init__(self, store):
        self.store = store

    def clear(self, **kwargs):
        return self

    def update(self, spreadsheetId, range, valueInputOption, body):
        self.store["values"] = body["values"]
        self._result = {"updatedCells": sum(len(r) for r in body["values"]),
                        "updatedRows": len(body["values"])}
        return self

    def get(self, spreadsheetId, range):
        self._result = {"values": self.store.get("values", [])}
        return self

    def execute(self):
        return getattr(self, "_result", {})


class FakeSpreadsheets:
    def __init__(self, store):
        self.store = store

    def create(self, body, fields):
        self.store["title"] = body["properties"]["title"]
        self._result = {"spreadsheetId": "SHEET123",
                        "spreadsheetUrl": "https://docs.google.com/spreadsheets/d/SHEET123"}
        return self

    def get(self, spreadsheetId, **kwargs):
        self._result = {"spreadsheetUrl": "https://docs.google.com/spreadsheets/d/SHEET123",
                        "sheets": [{"properties": {"title": "Employees", "sheetId": 0}}]}
        return self

    def batchUpdate(self, spreadsheetId, body):
        self._result = {"replies": [{"addSheet": {"properties": {"sheetId": 7}}}]}
        return self

    def values(self):
        return FakeValues(self.store)

    def execute(self):
        return self._result


class FakeService:
    def __init__(self):
        self.store = {}

    def spreadsheets(self):
        return FakeSpreadsheets(self.store)


@pytest.fixture
def fake_service(monkeypatch):
    service = FakeService()
    monkeypatch.setattr(sheets_tool, "build_service", lambda cfg: service)
    monkeypatch.setattr(sheets_tool, "_share", lambda sid, cfg: [])
    return service


def test_import_creates_sheet_and_writes_all_rows(ctx, fake_service):
    csv_result = generate_employee_csv(ctx=ctx, row_count=20, seed=2)
    result = import_csv_to_google_sheets(ctx=ctx, csv_path=csv_result["csv_path"])
    assert result["status"] == "success"
    assert result["spreadsheet_id"] == "SHEET123"
    assert result["data_rows"] == 20
    assert len(fake_service.store["values"]) == 21
    assert ctx.state["spreadsheet_id"] == "SHEET123"


def test_missing_csv_fails_cleanly(ctx, fake_service):
    result = import_csv_to_google_sheets(ctx=ctx, csv_path="/absent.csv")
    assert result["status"] == "failed"


def test_auth_error_is_not_retried(ctx, monkeypatch):
    attempts = {"n": 0}

    def boom(cfg):
        attempts["n"] += 1
        raise SheetsAuthError("credentials file not found")

    monkeypatch.setattr(sheets_tool, "build_service", boom)
    csv_result = generate_employee_csv(ctx=ctx, row_count=2, seed=2)
    result = import_csv_to_google_sheets(ctx=ctx, csv_path=csv_result["csv_path"])
    assert result["status"] == "failed"
    assert result["stage"] == "authentication"
    assert attempts["n"] == 1


def test_missing_credentials_file_raises_auth_error(ctx, tmp_path):
    ctx.config.sheets.credentials_file = str(tmp_path / "nope.json")
    with pytest.raises(SheetsAuthError):
        sheets_tool._credentials(ctx.config.sheets)


def test_verify_checks_both_targets(ctx, fake_service):
    from sheetagent.tools.excel_tool import import_csv_to_excel
    csv_result = generate_employee_csv(ctx=ctx, row_count=20, seed=4)
    import_csv_to_excel(ctx=ctx, csv_path=csv_result["csv_path"])
    import_csv_to_google_sheets(ctx=ctx, csv_path=csv_result["csv_path"])
    result = verify_imports(ctx=ctx, csv_path=csv_result["csv_path"])
    assert result["checks"]["excel"]["ok"] is True
    assert result["checks"]["google_sheets"]["ok"] is True
    assert result["all_verified"] is True


def test_verify_reports_missing_workbook(ctx):
    csv_result = generate_employee_csv(ctx=ctx, row_count=3, seed=4)
    result = verify_imports(ctx=ctx, csv_path=csv_result["csv_path"],
                            workbook_path="/gone.xlsx")
    assert result["status"] == "partial"
    assert result["checks"]["excel"]["ok"] is False


# --------------------------------------------------------------------------- #
# Retry classification: only genuinely transient failures may be retried.
# --------------------------------------------------------------------------- #
def _http_error(status: int, reason: str = "boom"):
    from googleapiclient.errors import HttpError
    resp = httplib2.Response({"status": status})
    resp.reason = reason
    err = HttpError(resp, b"{}")
    err.reason = reason
    return err


def _fail_inside_retry_scope(monkeypatch, exc, attempts):
    """Auth succeeds; the API call is what fails.

    Authentication now happens outside with_retry, so a test that raises from
    build_service would exercise the auth path, not the retry classification.
    """
    def boom(*a, **kw):
        attempts.append(1)
        raise exc

    monkeypatch.setattr(sheets_tool, "build_service", lambda cfg: object())
    monkeypatch.setattr(sheets_tool, "_ensure_spreadsheet", boom)
    monkeypatch.setattr(sheets_tool, "_share", lambda sid, cfg: [])
    monkeypatch.setattr(sheets_tool, "with_retry",
                        functools.partial(sheets_tool.with_retry, sleep=lambda _: None))


@pytest.mark.parametrize("status", [400, 403, 404])
def test_permanent_http_errors_are_not_retried(ctx, monkeypatch, status):
    attempts = []
    _fail_inside_retry_scope(monkeypatch, _http_error(status, "API has not been used"),
                             attempts)
    csv_result = generate_employee_csv(ctx=ctx, row_count=2, seed=1)
    result = import_csv_to_google_sheets(ctx=ctx, csv_path=csv_result["csv_path"])

    assert result["status"] == "failed"
    assert result["retryable"] is False
    assert str(status) in result["error"]
    assert len(attempts) == 1, "a permanent rejection must not be retried"


@pytest.mark.parametrize("status", [429, 500, 503])
def test_transient_http_errors_are_retried(ctx, monkeypatch, status):
    attempts = []
    _fail_inside_retry_scope(monkeypatch, _http_error(status, "backend error"), attempts)
    csv_result = generate_employee_csv(ctx=ctx, row_count=2, seed=1)
    result = import_csv_to_google_sheets(ctx=ctx, csv_path=csv_result["csv_path"])

    assert result["status"] == "failed"
    assert len(attempts) == ctx.config.retry.max_attempts


# --------------------------------------------------------------------------- #
# Authentication is resolved once, outside the retry scope. run_local_server()
# opens a real browser; retrying a cancelled prompt reopens it.
# --------------------------------------------------------------------------- #
def test_cancelled_oauth_flow_is_attempted_exactly_once(ctx, monkeypatch):
    """A cancelled browser prompt raises a plain Exception, not an HttpError.

    Before auth was hoisted this fell through to retry_on=(Exception,) and the
    browser reopened three times.
    """
    attempts = []

    def cancelled(cfg):
        attempts.append(1)
        raise Exception("access_denied: user cancelled the authorization flow")

    monkeypatch.setattr(sheets_tool, "build_service", cancelled)
    monkeypatch.setattr(sheets_tool, "with_retry",
                        functools.partial(sheets_tool.with_retry, sleep=lambda _: None))
    csv_result = generate_employee_csv(ctx=ctx, row_count=2, seed=7)
    result = import_csv_to_google_sheets(ctx=ctx, csv_path=csv_result["csv_path"])

    assert len(attempts) == 1, "the browser must not be reopened on retry"
    assert result["status"] == "failed"
    assert result["stage"] == "authentication"
    assert result["retryable"] is False


def test_auth_is_not_reattempted_when_the_api_call_retries(ctx, monkeypatch):
    """Retries must re-run the API call, never the auth flow."""
    auth_calls, api_calls = [], []

    def auth(cfg):
        auth_calls.append(1)
        return object()

    def api(*a, **kw):
        api_calls.append(1)
        raise _http_error(503, "backend error")

    monkeypatch.setattr(sheets_tool, "build_service", auth)
    monkeypatch.setattr(sheets_tool, "_ensure_spreadsheet", api)
    monkeypatch.setattr(sheets_tool, "with_retry",
                        functools.partial(sheets_tool.with_retry, sleep=lambda _: None))
    csv_result = generate_employee_csv(ctx=ctx, row_count=2, seed=8)
    import_csv_to_google_sheets(ctx=ctx, csv_path=csv_result["csv_path"])

    assert len(auth_calls) == 1
    assert len(api_calls) == ctx.config.retry.max_attempts


def test_credentials_are_cached_so_sharing_does_not_reauthenticate(ctx, tmp_path,
                                                                   monkeypatch):
    sheets_tool._reset_credential_cache()
    calls = []
    creds_file = tmp_path / "credentials.json"
    creds_file.write_text('{"type": "service_account"}', encoding="utf-8")
    ctx.config.sheets.credentials_file = str(creds_file)

    class FakeServiceCredentials:
        @staticmethod
        def from_service_account_file(path, scopes):
            calls.append(1)
            return "creds"

    import google.oauth2.service_account as sa
    monkeypatch.setattr(sa, "Credentials", FakeServiceCredentials)

    first = sheets_tool._credentials(ctx.config.sheets)
    second = sheets_tool._credentials(ctx.config.sheets)
    assert first is second
    assert len(calls) == 1, "the OAuth/service-account flow must run once per process"
    sheets_tool._reset_credential_cache()
