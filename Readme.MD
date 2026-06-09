# user_action_logs_python

Python port + extension of the feature-toggle log report. Step 1 builds the
SpotID list from Jira and writes it back to the Google Sheet.

## Flow

1. Read `entry_data` tab → list of names (column A) + time range (cell B2).
2. For each name, query Jira (cookie auth) with:

   ```
   created > -<timeRange> AND (
     watcher in ("<name>") OR assignee in ("<name>") OR
     reporter in ("<name>") OR creator in ("<name>")
   )
   ```
3. Pull the **SpotID** custom field off every matching issue, dedupe.
4. Write the deduped ids to the **`result`** tab, and also drop local
   `spot_ids.txt` (comma-separated) + `spot_ids_in_clause.sql`
   (a ready-to-paste `AND ... spot_id IN (...)` clause).

## Setup

```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1      # PowerShell
pip install -r requirements.txt
cp .env.example .env              # then fill in the values
```

### Google service account (needed to read AND write the sheet)

1. In Google Cloud, create a service account and enable the **Google Sheets API**.
2. Download its JSON key → save as `service_account.json` (gitignored).
3. Share the spreadsheet with the service account email (…@….iam.gserviceaccount.com)
   as **Editor**.
4. Local: point `GOOGLE_CREDS_FILE` at the JSON. CI: paste the JSON into the
   `GOOGLE_CREDS_JSON` secret instead.

With a service account the sheet can stay private — no link sharing required.

### Jira

- **JIRA_COOKIE** — log into Jira, dev tools → Application → Cookies, copy the
  `JSESSIONID=...` pair. Expires with your session; re-grab on 401/302.
- **SPOTID_FIELD** — the custom field id (`customfield_XXXXX`). Discover it once:
  ```python
  from jira_client import JiraClient
  c = JiraClient("<base>", "<cookie>", "x")
  print(c.find_field_id("SpotID"))
  ```

## Run

```bash
python main.py
```

## GitHub Actions (manual only)

`.github/workflows/fetch_spot_ids.yml` runs on **workflow_dispatch** only.
Add repo secrets: `JIRA_BASE_URL`, `JIRA_COOKIE`, `SPOTID_FIELD`, `SHEET_ID`,
`ENTRY_TAB`, `RESULT_TAB`, `GOOGLE_CREDS_JSON`, optionally `JIRA_VERIFY_SSL`.
Results are also uploaded as a downloadable artifact.

> Note: the Jira **cookie** expires fast and is awkward for CI. For reliable
> scheduled/automated runs, switch to a Jira API token + basic auth.

## Gotchas

- **Sheet layout:** names in column A (row 2 down), time range in B2.
  Adjust `name_col` / the B2 index in `sheets_client.py` if yours differs.
- **JQL time unit:** a bare `180` in B2 is read as *minutes*. Use `180d`.
- Never commit `.env` or `service_account.json` (both gitignored).