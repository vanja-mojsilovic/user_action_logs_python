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


def read_entry_data(spreadsheet_id: str, tab: str = "entry_data",
                    name_col: int = 0) -> Tuple[str, List[str]]:
    """Return (time_range, names).

    Layout assumed: time range in B2; names down column A from row 2.
    Adjust name_col (0 = column A) and the B2 index if your sheet differs.
    """
    ws = _open(spreadsheet_id).worksheet(tab)
    rows = ws.get_all_values()
    if len(rows) < 2:
        raise RuntimeError(f"'{tab}' has no data rows.")

    time_range = rows[1][1].strip() if len(rows[1]) > 1 else ""  # B2
    names = [
        row[name_col].strip()
        for row in rows[1:]
        if len(row) > name_col and row[name_col].strip()
    ]
    return time_range, names


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