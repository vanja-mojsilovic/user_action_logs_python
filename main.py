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
    time_range, names, emails = read_entry_data(sheet_id, tab=entry_tab)
    # `emails` (column B) isn't needed for the Jira step, but will drive the
    # user_action_logs email filter in the next stage.

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

    # --- DEBUG probes ---
    bu = base_url.rstrip("/")

    print("\n[debug] probe 0 — who am I authenticated as? (/myself)")
    pm = jira.session.get(f"{bu}/rest/api/3/myself")
    print(f"  HTTP {pm.status_code}")
    try:
        me = pm.json()
        print(f"  accountId={me.get('accountId')} | email={me.get('emailAddress')!r} "
              f"| name={me.get('displayName')!r}")
    except Exception as exc:
        print("  parse error:", exc, pm.text[:300])

    print("\n[debug] probe A — bounded query, NO user filter (do I see any issues?):")
    pa = jira.session.get(
        f"{bu}/rest/api/3/search/jql",
        params={"jql": f"created > -{time_range} ORDER BY created DESC",
                "maxResults": 3, "fields": f"created,{spotid_field}"},
    )
    print(f"  HTTP {pa.status_code}")
    try:
        d = pa.json()
        print(f"  issues returned: {len(d.get('issues', []))}  isLast={d.get('isLast')}")
        for it in d.get("issues", []):
            print(f"    {it.get('key')} | {spotid_field}="
                  f"{it.get('fields', {}).get(spotid_field)!r}")
        if d.get("errorMessages"):
            print("  errorMessages:", d["errorMessages"])
    except Exception as exc:
        print("  parse error:", exc, pa.text[:300])

    print("\n[debug] probe B — does this login resolve the display name 'Nikola Milosevic'?")
    pb = jira.session.get(f"{bu}/rest/api/3/user/search",
                          params={"query": "Nikola Milosevic", "maxResults": 5})
    print(f"  HTTP {pb.status_code}")
    try:
        for u in pb.json():
            print(f"    {u.get('displayName')!r} | accountId={u.get('accountId')} | "
                  f"active={u.get('active')}")
        if not pb.json():
            print("    (no users matched — name resolution is the problem)")
    except Exception as exc:
        print("  parse error:", exc, pb.text[:300])
    print("[debug] end probes\n")

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