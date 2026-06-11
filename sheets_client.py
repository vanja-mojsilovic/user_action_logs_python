"""Read 'entry_data' and write 'result' on the Google Sheet via a service account.

Setup (one time):
  1. In Google Cloud, create a service account and enable the Google Sheets API.
  2. Download its JSON key.
  3. Share the spreadsheet with the service account's email (e.g.
     my-sa@project.iam.gserviceaccount.com) as **Editor**.
  4. Point GOOGLE_CREDS_FILE at the JSON, or put the JSON content in
     GOOGLE_CREDS_JSON (handy for CI secrets).

With a service account the sheet can stay private — no link sharing needed.
"""
import json
import os
from typing import List, Tuple

import gspread
from google.oauth2.service_account import Credentials

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def _credentials() -> Credentials:
    raw = os.environ.get("GOOGLE_CREDS_JSON", "").strip()
    if raw:
        return Credentials.from_service_account_info(json.loads(raw), scopes=SCOPES)
    path = os.environ.get("GOOGLE_CREDS_FILE", "").strip()
    if path:
        return Credentials.from_service_account_file(path, scopes=SCOPES)
    raise RuntimeError("Set GOOGLE_CREDS_JSON or GOOGLE_CREDS_FILE for sheet access.")


def _open(spreadsheet_id: str):
    return gspread.authorize(_credentials()).open_by_key(spreadsheet_id)


def read_entry_data(spreadsheet_id: str, tab: str = "entry_data"):
    """Return (time_range, names, emails).

    Layout: header row with 'Assignee', 'Email', 'Period'. Names come from the
    Assignee column, one email per name from the Email column, and the time
    range from the Period column (first non-empty value, e.g. cell C2).
    Columns are located by header so reordering won't break it; falls back to
    A/B/C positions if a header is missing.
    """
    ws = _open(spreadsheet_id).worksheet(tab)
    rows = ws.get_all_values()
    if len(rows) < 2:
        raise RuntimeError(f"'{tab}' has no data rows.")

    header = [h.strip().lower() for h in rows[0]]

    def col(name: str, default: int) -> int:
        return header.index(name) if name in header else default

    a_col, e_col, p_col = col("assignee", 0), col("email", 1), col("period", 2)

    time_range = ""
    for r in rows[1:]:
        if len(r) > p_col and r[p_col].strip():
            time_range = r[p_col].strip()
            break

    names = [r[a_col].strip() for r in rows[1:] if len(r) > a_col and r[a_col].strip()]
    emails = [r[e_col].strip() for r in rows[1:] if len(r) > e_col and r[e_col].strip()]
    return time_range, names, emails


def write_results(spreadsheet_id: str, spot_ids: List[int], tab: str = "result",
                  header: str = "Custom field (SpotID)") -> int:
    """Write the deduped spot ids to the result tab, one per row under a header.
    Creates the tab if it doesn't exist; clears it first otherwise."""
    sh = _open(spreadsheet_id)
    try:
        ws = sh.worksheet(tab)
        ws.clear()
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=tab, rows=len(spot_ids) + 10, cols=2)

    values = [[header]] + [[sid] for sid in spot_ids]
    ws.update(values=values, range_name="A1")
    return len(spot_ids)


def read_column(spreadsheet_id: str, tab: str, col: int = 0,
                skip_header: bool = True) -> List[str]:
    """Read one column of values from a tab (defaults to column A, skipping the header)."""
    ws = _open(spreadsheet_id).worksheet(tab)
    rows = ws.get_all_values()
    start = 1 if skip_header else 0
    return [r[col].strip() for r in rows[start:] if len(r) > col and r[col].strip()]


def write_table(spreadsheet_id: str, header: List[str], rows: List[List],
                tab: str) -> int:
    """Write a header row + data rows to a tab. Creates it if missing, clears it first."""
    sh = _open(spreadsheet_id)
    try:
        ws = sh.worksheet(tab)
        ws.clear()
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=tab, rows=len(rows) + 10, cols=max(2, len(header)))
    ws.update(values=[header] + rows, range_name="A1")
    return len(rows)


def read_records(spreadsheet_id: str, tab: str) -> List[dict]:
    """Read a tab as a list of dicts keyed by the header row (spot_id, user_email, ...)."""
    ws = _open(spreadsheet_id).worksheet(tab)
    return ws.get_all_records()


def write_table_keep_header(spreadsheet_id: str, header: List[str],
                            rows: List[List], tab: str) -> int:
    """Clear everything from row 2 down, then write data starting at A2.
    Row 1 is refreshed with the given header (overwritten, not cleared), so any
    formatting on the header row survives."""
    sh = _open(spreadsheet_id)
    try:
        ws = sh.worksheet(tab)
        # clear from the second row to the bottom, across all columns
        ws.batch_clear([f"A2:{gspread.utils.rowcol_to_a1(ws.row_count, ws.col_count)}"])
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=tab, rows=len(rows) + 10, cols=max(2, len(header)))
    ws.update(values=[header], range_name="A1")
    if rows:
        ws.update(values=rows, range_name="A2")
    return len(rows)