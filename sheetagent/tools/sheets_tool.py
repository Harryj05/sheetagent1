"""Tool: push the same CSV into a Google Sheet via the Sheets API v4.

Auth supports both flows:
  * service account  (credentials.json with "type": "service_account") - no
    browser, ideal for unattended runs; remember to share the target sheet
    with the service-account email, or set sheets.share_with in config.
  * installed-app OAuth (client_secret.json) - opens a browser once and caches
    token.json.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ..registry import ToolContext, tool
from ..retry import with_retry
from .excel_tool import read_csv

log = logging.getLogger("sheetagent.tools.sheets")

SCOPES = ["https://www.googleapis.com/auth/spreadsheets",
          "https://www.googleapis.com/auth/drive.file"]


class SheetsAuthError(RuntimeError):
    """Configuration problem - retrying will not help."""


class SheetsPermanentError(RuntimeError):
    """An API rejection that will be rejected identically on every retry."""


#: 408 and 429 are the two 4xx codes that genuinely change on their own.
_TRANSIENT_STATUSES = {408, 429}


def _classify(exc: Exception) -> Exception:
    """Turn a Google HttpError into something ``with_retry`` can classify.

    Without this every failure looks retryable, so a 403 'API not enabled' or a
    404 'no such spreadsheet' burns three attempts and then surfaces as an
    opaque RetryExhausted instead of the actionable message Google sent back.
    """
    try:
        from googleapiclient.errors import HttpError
    except ImportError:
        return exc
    if not isinstance(exc, HttpError):
        return exc
    status = getattr(getattr(exc, "resp", None), "status", None)
    if status is None or status >= 500 or status in _TRANSIENT_STATUSES:
        return exc  # transient - let the backoff do its job
    detail = getattr(exc, "reason", None) or str(exc)
    hint = ""
    if status == 403:
        hint = (" Enable the Google Sheets API (and the Drive API if "
                "sheets.share_with is set) for this project, and confirm the "
                "service account may access the spreadsheet.")
    elif status == 404:
        hint = " Check sheets.spreadsheet_id - leave it blank to create a new sheet."
    return SheetsPermanentError(f"Google API returned {status}: {detail}.{hint}")


#: Resolved credentials, keyed by the files they came from. Authentication is a
#: once-per-process concern: the OAuth flow opens a real browser, and _share and
#: verify_imports both need credentials after the import has already resolved
#: them. Keyed rather than a single slot so a test (or a caller that switches
#: config) cannot silently inherit another config's credentials.
_CREDENTIAL_CACHE: dict[tuple[str, str], Any] = {}


def _reset_credential_cache() -> None:
    """Test hook - production code has no reason to call this."""
    _CREDENTIAL_CACHE.clear()


def _credentials(cfg) -> Any:
    try:
        from google.oauth2.credentials import Credentials
        from google.oauth2.service_account import Credentials as ServiceCredentials
        from google.auth.transport.requests import Request
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError as exc:
        raise SheetsAuthError(
            "Google client libraries missing; pip install -r requirements.txt"
        ) from exc

    cred_path = Path(cfg.credentials_file).expanduser()
    cache_key = (str(cred_path), str(cfg.token_file))
    if cache_key in _CREDENTIAL_CACHE:
        return _CREDENTIAL_CACHE[cache_key]
    if not cred_path.exists():
        raise SheetsAuthError(
            f"credentials file not found: {cred_path}. See README section "
            "'Google Sheets setup'."
        )

    try:
        blob = json.loads(cred_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SheetsAuthError(f"{cred_path} is not valid JSON: {exc}") from exc

    if blob.get("type") == "service_account":
        creds = ServiceCredentials.from_service_account_file(str(cred_path), scopes=SCOPES)
        _CREDENTIAL_CACHE[cache_key] = creds
        return creds

    token_path = Path(cfg.token_file).expanduser()
    creds = None
    if token_path.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        except Exception as exc:
            log.warning("ignoring unreadable token file: %s", exc)
    if creds and creds.valid:
        _CREDENTIAL_CACHE[cache_key] = creds
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        flow = InstalledAppFlow.from_client_secrets_file(str(cred_path), SCOPES)
        creds = flow.run_local_server(port=0)
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    _CREDENTIAL_CACHE[cache_key] = creds
    return creds


def build_service(cfg):
    try:
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise SheetsAuthError(
            "google-api-python-client is not installed; "
            "run pip install -r requirements.txt"
        ) from exc
    return build("sheets", "v4", credentials=_credentials(cfg), cache_discovery=False)


def _ensure_spreadsheet(service, cfg, title: str) -> tuple[str, str, bool]:
    """Return (spreadsheet_id, url, created)."""
    if cfg.spreadsheet_id:
        meta = service.spreadsheets().get(spreadsheetId=cfg.spreadsheet_id).execute()
        return cfg.spreadsheet_id, meta["spreadsheetUrl"], False
    created = service.spreadsheets().create(
        body={"properties": {"title": title},
              "sheets": [{"properties": {"title": cfg.worksheet_title}}]},
        fields="spreadsheetId,spreadsheetUrl",
    ).execute()
    return created["spreadsheetId"], created["spreadsheetUrl"], True


def _ensure_worksheet(service, spreadsheet_id: str, title: str) -> int:
    meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    for sheet in meta.get("sheets", []):
        if sheet["properties"]["title"] == title:
            return sheet["properties"]["sheetId"]
    response = service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": [{"addSheet": {"properties": {"title": title}}}]},
    ).execute()
    return response["replies"][0]["addSheet"]["properties"]["sheetId"]


def _share(spreadsheet_id: str, cfg) -> list[str]:
    if not cfg.share_with:
        return []
    from googleapiclient.discovery import build
    drive = build("drive", "v3", credentials=_credentials(cfg), cache_discovery=False)
    shared = []
    for email in cfg.share_with:
        try:
            drive.permissions().create(
                fileId=spreadsheet_id,
                body={"type": "user", "role": "writer", "emailAddress": email},
                sendNotificationEmail=False,
            ).execute()
            shared.append(email)
        except Exception as exc:  # sharing failure must not fail the import
            log.warning("could not share with %s: %s", email, exc)
    return shared


@tool(
    name="import_csv_to_google_sheets",
    description=(
        "Upload the rows of a CSV file into a Google Sheet using the Google "
        "Sheets API v4. Creates a new spreadsheet unless a spreadsheet_id is "
        "given or configured, writes the header plus every data row, bolds and "
        "freezes the header, and returns the spreadsheet URL."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "csv_path": {"type": "string",
                         "description": "Path to the CSV produced by generate_employee_csv."},
            "spreadsheet_title": {"type": "string",
                                  "description": "Title used when creating a new spreadsheet."},
            "spreadsheet_id": {"type": "string",
                               "description": "Write into this existing spreadsheet instead of creating one."},
            "worksheet_title": {"type": "string", "default": "Employees"},
        },
        "required": ["csv_path"],
    },
)
def import_csv_to_google_sheets(ctx: ToolContext, csv_path: str,
                                spreadsheet_title: str | None = None,
                                spreadsheet_id: str | None = None,
                                worksheet_title: str | None = None) -> dict[str, Any]:
    cfg = ctx.config.sheets
    source = Path(csv_path).expanduser()
    if not source.exists():
        return {"status": "failed", "error": f"CSV not found: {source}",
                "hint": "Run generate_employee_csv first."}

    if spreadsheet_id:
        cfg.spreadsheet_id = spreadsheet_id
    sheet_title = worksheet_title or cfg.worksheet_title
    title = spreadsheet_title or f"Employee Data - {source.stem}"

    header, body = read_csv(source)
    values = [header, *body]

    # --- authenticate ONCE, outside the retry scope --------------------------
    # run_local_server() opens a real browser. Inside with_retry, cancelling
    # that prompt raises a non-HttpError and the browser reopens on every
    # attempt. Credentials are also not something a retry can fix: either they
    # resolve or they do not.
    try:
        service = build_service(cfg)
    except SheetsAuthError as exc:
        return {"status": "failed", "error": str(exc), "stage": "authentication",
                "retryable": False}
    except Exception as exc:
        return {"status": "failed",
                "error": f"{type(exc).__name__}: {exc}",
                "stage": "authentication", "retryable": False}

    def _run() -> dict[str, Any]:
        sid, url, created = _ensure_spreadsheet(service, cfg, title)
        ctx.events.emit("step_progress",
                        f"{'Created' if created else 'Opened'} spreadsheet {sid}",
                        spreadsheet_id=sid)
        gid = _ensure_worksheet(service, sid, sheet_title)
        service.spreadsheets().values().clear(
            spreadsheetId=sid, range=f"'{sheet_title}'!A:ZZ", body={}).execute()
        update = service.spreadsheets().values().update(
            spreadsheetId=sid,
            range=f"'{sheet_title}'!A1",
            valueInputOption="USER_ENTERED",
            body={"values": values},
        ).execute()
        service.spreadsheets().batchUpdate(spreadsheetId=sid, body={"requests": [
            {"repeatCell": {
                "range": {"sheetId": gid, "startRowIndex": 0, "endRowIndex": 1},
                "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                "fields": "userEnteredFormat.textFormat.bold"}},
            {"updateSheetProperties": {
                "properties": {"sheetId": gid,
                               "gridProperties": {"frozenRowCount": 1}},
                "fields": "gridProperties.frozenRowCount"}},
            {"autoResizeDimensions": {
                "dimensions": {"sheetId": gid, "dimension": "COLUMNS",
                               "startIndex": 0, "endIndex": len(header)}}},
        ]}).execute()
        return {"spreadsheet_id": sid, "spreadsheet_url": url, "created": created,
                "worksheet_title": sheet_title,
                "updated_cells": update.get("updatedCells"),
                "updated_rows": update.get("updatedRows")}

    def _run_classified() -> dict[str, Any]:
        try:
            return _run()
        except Exception as exc:
            raise _classify(exc) from exc

    try:
        details = with_retry(
            _run_classified,
            max_attempts=ctx.config.retry.max_attempts,
            initial_delay=ctx.config.retry.initial_delay,
            backoff=ctx.config.retry.backoff,
            max_delay=ctx.config.retry.max_delay,
            give_up_on=(SheetsAuthError, SheetsPermanentError),
            label="google-sheets-import",
        )
    except SheetsAuthError as exc:  # defensive: auth is resolved above
        return {"status": "failed", "error": str(exc), "stage": "authentication",
                "retryable": False}
    except SheetsPermanentError as exc:
        return {"status": "failed", "error": str(exc), "stage": "api_call",
                "retryable": False}
    except Exception as exc:
        return {"status": "failed", "error": f"{type(exc).__name__}: {exc}",
                "stage": "api_call"}

    shared = _share(details["spreadsheet_id"], cfg)
    ctx.state["spreadsheet_id"] = details["spreadsheet_id"]
    ctx.state["spreadsheet_url"] = details["spreadsheet_url"]
    return {
        "status": "success",
        **details,
        "shared_with": shared,
        "data_rows": len(body),
        "summary": (f"Wrote {len(body)} rows to Google Sheet "
                    f"{details['spreadsheet_url']}"),
    }
