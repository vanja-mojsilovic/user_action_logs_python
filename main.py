"""Step 1 of the pipeline: build the SpotID list from Jira.

Reads names + time range from the Google Sheet's 'entry_data' tab, queries
Jira Cloud per name (API-token auth), dedupes the SpotIDs, writes them to the
'result' tab of the same sheet, and also drops a comma-separated file + a
ready-to-paste SQL IN(...) clause locally.
"""
import os
import sys
from dotenv import load_dotenv

from sheets_client import read_entry_data, write_results
from jira_client import JiraClient

load_dotenv()


def normalize_time_range(time_range: str) -> str:
    """JQL gotcha: a bare number is read as MINUTES, not days. Warn if no unit."""
    if time_range and time_range.lstrip("-").isdigit():
        print(f"  WARNING: time range '{time_range}' has no unit -> Jira reads it as "
              f"MINUTES. Put '{time_range}d' in B2 for days.")
    return time_range


def main():
    base_url = os.environ["JIRA_BASE_URL"]
    email = os.environ["JIRA_EMAIL"]
    api_token = os.environ["JIRA_API_TOKEN"]
    # SpotID custom field is instance-wide, not a secret — hardcoded default.
    # Can still be overridden via the SPOTID_FIELD env var if it ever changes.
    spotid_field = os.environ.get("SPOTID_FIELD") or "customfield_10053"
    sheet_id = os.environ["SHEET_ID"]
    entry_tab = os.environ.get("ENTRY_TAB") or "entry_data"
    result_tab = os.environ.get("RESULT_TAB") or "result"
    verify = os.environ.get("JIRA_VERIFY_SSL", "true").lower() != "false"

    print("Reading entry_data from Google Sheet...")
    time_range, names = read_entry_data(sheet_id, tab=entry_tab)

    # Optional override (e.g. from the manual GitHub Actions input)
    override = os.environ.get("TIME_RANGE_OVERRIDE", "").strip()
    if override:
        print(f"  using time range override: {override!r}")
        time_range = override

    time_range = normalize_time_range(time_range)
    print(f"  time range: {time_range!r}, {len(names)} name(s)")

    if not names:
        sys.exit("No names found in the sheet — check the column layout in sheets_client.py.")

    print("Querying Jira per name...")
    jira = JiraClient(base_url, email, api_token, spotid_field, verify=verify)

    # --- DEBUG control probe: does this login see ANY issues at all? ---
    print("\n[debug] control probe (no user filter, 3 most recent issues):")
    probe = jira.session.get(
        f"{base_url.rstrip('/')}/rest/api/3/search/jql",
        params={"jql": "ORDER BY created DESC", "maxResults": 3,
                "fields": f"created,{spotid_field}"},
    )
    print(f"  HTTP {probe.status_code}")
    try:
        pdata = probe.json()
        print(f"  issues returned: {len(pdata.get('issues', []))}  "
              f"isLast={pdata.get('isLast')}")
        for it in pdata.get("issues", []):
            f = it.get("fields", {})
            print(f"    {it.get('key')} | {spotid_field}={f.get(spotid_field)!r}")
        if pdata.get("errorMessages"):
            print("  errorMessages:", pdata["errorMessages"])
    except Exception as exc:
        print("  could not parse probe response:", exc, probe.text[:300])
    print("[debug] end control probe\n")

    spot_ids = sorted(jira.spot_ids_for_names(names, time_range))
    print(f"\nTotal unique spot ids: {len(spot_ids)}")

    # Write back to the 'result' tab
    print(f"Writing {len(spot_ids)} spot id(s) to '{result_tab}' tab...")
    write_results(sheet_id, spot_ids, tab=result_tab)

    # Local copies for convenience / the SQL step
    csv_line = ",".join(str(i) for i in spot_ids)
    with open("spot_ids.txt", "w") as f:
        f.write(csv_line)
    with open("spot_ids_in_clause.sql", "w") as f:
        f.write(f"AND user_action_logs.spot_id IN ({csv_line})\n")

    print("Done. Wrote 'result' tab, spot_ids.txt, and spot_ids_in_clause.sql")


if __name__ == "__main__":
    main()