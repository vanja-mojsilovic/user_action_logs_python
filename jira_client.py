"""Fetch SpotIDs from Jira Cloud.

Jira Cloud uses API-token auth (your Atlassian account email + an API token,
sent as HTTP basic auth). Create a token at:
  https://id.atlassian.com/manage-profile/security/api-tokens

Search uses the current Cloud endpoint /rest/api/3/search/jql with
token-based pagination (nextPageToken); the old startAt/total model is gone.
"""
import json
import requests
from typing import Iterable, Iterator, List, Set


def build_jql(name: str, time_range: str) -> str:
    """Build the per-person JQL. `name` is a single Jira display name / account."""
    return (
        f'created > -{time_range} AND ('
        f'watcher in ("{name}") OR '
        f'assignee in ("{name}") OR '
        f'reporter in ("{name}") OR '
        f'creator in ("{name}"))'
    )


def _extract_ids(value) -> List[int]:
    """A custom field can come back as a number, a string, an object, or a list.
    Pull every integer-looking SpotID out of whatever shape it is."""
    out: List[int] = []
    if value is None or isinstance(value, bool):
        return out
    if isinstance(value, (int, float)):
        out.append(int(value))
    elif isinstance(value, str):
        for token in value.replace(",", " ").split():
            if token.strip().isdigit():
                out.append(int(token.strip()))
    elif isinstance(value, dict):
        out.extend(_extract_ids(value.get("value")))
        out.extend(_extract_ids(value.get("name")))
    elif isinstance(value, list):
        for item in value:
            out.extend(_extract_ids(item))
    return out


class JiraClient:
    def __init__(self, base_url: str, email: str, api_token: str,
                 spotid_field: str, verify: bool = True):
        self.base_url = base_url.rstrip("/")
        self.spotid_field = spotid_field
        self.session = requests.Session()
        self.session.auth = (email, api_token)  # Cloud basic auth: email + API token
        self.session.headers.update({"Accept": "application/json"})
        self.session.verify = verify

    def find_field_id(self, field_name: str):
        """Discover the SpotID custom field id (run once, then set SPOTID_FIELD).
        Returns e.g. [{'id': 'customfield_12345', 'name': 'SpotID'}, ...]."""
        resp = self.session.get(f"{self.base_url}/rest/api/3/field")
        resp.raise_for_status()
        return [f for f in resp.json() if field_name.lower() in f.get("name", "").lower()]

    def search_issues(self, jql: str, page_size: int = 100,
                      max_pages: int = 1000) -> Iterator[dict]:
        """Yield every issue matching the JQL via the Cloud /search/jql endpoint.
        Paginates with nextPageToken; guards against the known token-loop bug."""
        url = f"{self.base_url}/rest/api/3/search/jql"
        next_token = None
        seen_tokens: Set[str] = set()
        pages = 0

        while True:
            params = {
                "jql": jql,
                "maxResults": page_size,
                "fields": self.spotid_field,
            }
            if next_token:
                params["nextPageToken"] = next_token

            resp = self.session.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

            for issue in data.get("issues", []):
                yield issue

            pages += 1
            if data.get("isLast", True):
                break
            next_token = data.get("nextPageToken")
            # Loop guards: no token, repeated token, or runaway page count
            if not next_token or next_token in seen_tokens or pages >= max_pages:
                break
            seen_tokens.add(next_token)

    def spot_ids_for_name(self, name: str, time_range: str):
        """Returns (ids, issue_count, sample_issue) for diagnostics."""
        ids: Set[int] = set()
        issue_count = 0
        sample = None
        for issue in self.search_issues(build_jql(name, time_range)):
            issue_count += 1
            if sample is None:
                sample = issue
            ids.update(_extract_ids(issue.get("fields", {}).get(self.spotid_field)))
        return ids, issue_count, sample

    def spot_ids_for_names(self, names: Iterable[str], time_range: str) -> Set[int]:
        all_ids: Set[int] = set()
        first_sample = None
        for name in names:
            ids, count, sample = self.spot_ids_for_name(name, time_range)
            if first_sample is None and sample is not None:
                first_sample = sample
            print(f"  {name}: {count} issue(s), {len(ids)} spot id(s)")
            all_ids.update(ids)
        if first_sample is not None:
            print("\n  [debug] first issue's raw fields (looking for "
                  f"{self.spotid_field}):")
            print("  " + json.dumps(first_sample.get("fields", {}), indent=2)[:1800])
        return all_ids