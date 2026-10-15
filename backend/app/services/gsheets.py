# Author: Rajveer Sharma
# © NxtWave
# Date: 14 October 2026
"""Read a Google Sheet tab as rows.

Two modes:
- Service account (recommended; sheet stays private): pass a service-account JSON key
  file and share the sheet with the service account's email (Viewer). Needs the
  optional `sheets` extra: pip install -e ".[sheets]".
- Public link: if no credentials are given, the sheet must be shared as
  "Anyone with the link can view"; it is downloaded as CSV.

The tab is chosen by the `gid` in the URL (the part after #gid=), else the first tab.
"""

import csv
import io
import re
import urllib.error
import urllib.request
from urllib.parse import quote

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
SHEETS_API = "https://sheets.googleapis.com/v4/spreadsheets"

_SHEET_ID = re.compile(r"docs\.google\.com/spreadsheets/d/([A-Za-z0-9_-]+)")
_GID = re.compile(r"[#?&]gid=(\d+)")


class SheetError(Exception):
    pass


def is_sheet_url(source: str) -> bool:
    return bool(_SHEET_ID.search(source))


def parse_sheet_url(url: str) -> tuple[str, int | None]:
    m = _SHEET_ID.search(url)
    if not m:
        raise SheetError(f"not a Google Sheets URL: {url}")
    gid = _GID.search(url)
    return m.group(1), int(gid.group(1)) if gid else None


def fetch_rows(url: str, *, credentials_file: str | None = None) -> list[list[str]]:
    sheet_id, gid = parse_sheet_url(url)
    if credentials_file:
        return _fetch_with_service_account(sheet_id, gid, credentials_file)
    return _fetch_public_csv(sheet_id, gid)


def _fetch_public_csv(sheet_id: str, gid: int | None) -> list[list[str]]:
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
    if gid is not None:
        url += f"&gid={gid}"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            content_type = resp.headers.get("content-type", "")
            body = resp.read()
    except urllib.error.HTTPError as e:
        raise SheetError(_not_shared_msg(f"HTTP {e.code}")) from e
    except urllib.error.URLError as e:
        raise SheetError(f"could not reach Google Sheets: {e.reason}") from e
    if "text/csv" not in content_type:
        # private sheets redirect to a Google sign-in page
        raise SheetError(_not_shared_msg(f"got {content_type or 'non-CSV'} instead of CSV"))
    return list(csv.reader(io.StringIO(body.decode("utf-8-sig"))))


def _not_shared_msg(detail: str) -> str:
    return (
        f"could not download the sheet as CSV ({detail}). Either share it as "
        "'Anyone with the link can view', or pass --google-credentials with a "
        "service-account key and share the sheet with that account's email."
    )


def _fetch_with_service_account(sheet_id: str, gid: int | None, key_file: str) -> list[list[str]]:
    try:
        from google.auth.transport.requests import AuthorizedSession
        from google.oauth2 import service_account
    except ImportError as e:
        raise SheetError(
            "service-account mode needs the 'sheets' extra: pip install -e \".[sheets]\""
        ) from e

    try:
        creds = service_account.Credentials.from_service_account_file(key_file, scopes=SCOPES)
    except (OSError, ValueError) as e:
        raise SheetError(f"can't load service-account key {key_file}: {e}") from e
    session = AuthorizedSession(creds)

    meta = _get(session, f"{SHEETS_API}/{sheet_id}", {"fields": "sheets.properties(sheetId,title)"},
                creds.service_account_email)
    tabs = [s["properties"] for s in meta.get("sheets", [])]
    if not tabs:
        raise SheetError("spreadsheet has no tabs")
    tab = tabs[0] if gid is None else next((t for t in tabs if t["sheetId"] == gid), None)
    if tab is None:
        raise SheetError(f"no tab with gid={gid}; tabs: {[t['title'] for t in tabs]}")

    a1 = "'" + tab["title"].replace("'", "''") + "'"
    data = _get(session, f"{SHEETS_API}/{sheet_id}/values/{quote(a1, safe='')}",
                {"valueRenderOption": "FORMATTED_VALUE"}, creds.service_account_email)
    return [[str(c) for c in row] for row in data.get("values", [])]


def _get(session, url: str, params: dict, account_email: str) -> dict:
    resp = session.get(url, params=params, timeout=30)
    if resp.status_code in (403, 404):
        raise SheetError(
            f"Google Sheets API returned {resp.status_code}. Share the sheet (Viewer) with "
            f"{account_email} and make sure the Sheets API is enabled for its project."
        )
    if resp.status_code != 200:
        raise SheetError(f"Google Sheets API error {resp.status_code}: {resp.text[:300]}")
    return resp.json()
