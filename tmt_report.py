"""Build the TMT report.

Reads the pgAdmin export from the 'pg_admin' tab (columns: spot_id, user_email,
action_name), keeps only rows by QA team members (emails from the 'entry_data'
tab), counts enabled/disabled per service per spot, and writes the result to
the 'tmt_report' tab.

Services (each its own enabled/disabled pair):
  reservations, parties, jobs, catering, online_orders, online_ordering

'online_orders'  = "TMT Feature Enabled/Disabled - Online Orders"
'online_ordering'= the separate two-step "online_ordering feature activated/deactivated"
(kept as a separate column per the agreed spec).
"""
import os
from collections import defaultdict
from datetime import datetime, timezone
from dotenv import load_dotenv

from sheets_client import read_entry_data, read_records, write_table_keep_header

load_dotenv()

SHEET_ID = os.environ["SHEET_ID"]
ENTRY_TAB = os.environ.get("ENTRY_TAB") or "entry_data"
PG_ADMIN_TAB = os.environ.get("PG_ADMIN_TAB") or "pg_admin"
TMT_REPORT_TAB = os.environ.get("TMT_REPORT_TAB") or "tmt_report"

# maps the service text in "TMT Feature ... - <Service>" to our column key
SERVICE_MAP = {
    "reservations": "reservations",
    "private parties": "parties",
    "job listings": "jobs",
    "catering": "catering",
    "online orders": "online_orders",
}
SERVICES = ["reservations", "parties", "jobs", "catering",
            "online_orders", "online_ordering"]
STATES = ("enabled", "disabled")


def classify(action: str):
    """Return (service_key, state) for a relevant action, else None."""
    a = (action or "").strip()
    low = a.lower()

    # Separate two-step online_ordering feature (NOT the TMT 'Online Orders' line)
    if "ordering feature activated" in low:
        return ("online_ordering", "enabled")
    if "ordering feature deactivated" in low:
        return ("online_ordering", "disabled")

    # TMT Feature Enabled/Disabled - <Service>  (skip Embedded variants)
    if "tmt feature" in low and "embedded" not in low:
        parts = a.split(" - ")
        if len(parts) >= 2:
            verb, svc = parts[0].lower(), parts[1].strip().lower()
            key = SERVICE_MAP.get(svc)
            if key:
                if "enabled" in verb:
                    return (key, "enabled")
                if "disabled" in verb:
                    return (key, "disabled")
    return None


def empty_counts():
    return {f"{s}_{st}": 0 for s in SERVICES for st in STATES}


def main():
    _, _, emails = read_entry_data(SHEET_ID, tab=ENTRY_TAB)
    qa = {e.strip().lower() for e in emails if e.strip()}
    print(f"QA team: {len(qa)} email(s)")

    records = read_records(SHEET_ID, PG_ADMIN_TAB)
    print(f"'{PG_ADMIN_TAB}' rows: {len(records)}")

    counts = defaultdict(empty_counts)
    skipped_non_qa = 0
    skipped_unmatched = 0
    for rec in records:
        email = str(rec.get("user_email", "")).strip().lower()
        if email not in qa:
            skipped_non_qa += 1
            continue
        result = classify(str(rec.get("action_name", "")))
        if result is None:
            skipped_unmatched += 1
            continue
        service, state = result
        counts[str(rec.get("spot_id"))][f"{service}_{state}"] += 1

    print(f"  skipped (non-QA email): {skipped_non_qa}")
    print(f"  skipped (not a tracked action): {skipped_unmatched}")
    print(f"  spots with activity: {len(counts)}")

    run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    header = (["spot_id"] + [f"{s}_{st}" for s in SERVICES for st in STATES]
              + ["issue", "timestamp"])
    rows = []
    issue_count = 0
    for spot in sorted(counts, key=lambda x: int(x) if str(x).isdigit() else 0):
        c = counts[spot]
        # issue = any service whose enabled count != disabled count
        issue = any(c[f"{s}_enabled"] != c[f"{s}_disabled"] for s in SERVICES)
        if issue:
            issue_count += 1
        issue_text = "TRUE" if issue else "false"
        row = ([spot] + [c[f"{s}_{st}"] for s in SERVICES for st in STATES]
               + [issue_text, run_ts])
        rows.append(row)

    print(f"  spots flagged with an issue: {issue_count}")
    n = write_table_keep_header(SHEET_ID, header, rows, TMT_REPORT_TAB)
    print(f"Wrote {n} spot row(s) to '{TMT_REPORT_TAB}' at {run_ts}.")


if __name__ == "__main__":
    main()