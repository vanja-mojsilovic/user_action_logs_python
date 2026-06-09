"""Fetch SpotIDs from Jira using session-cookie authentication.

Jira Server / Data Center accepts a browser session cookie (JSESSIONID).
Grab it from your browser's dev tools (Application > Cookies) while logged in,
and put the whole cookie string in JIRA_COOKIE in your .env.
"""
import requests
from typing import Iterable, Iterator, Set, List


def build_jql(name: str, time_range: str) -> str:
    """Build the per-person JQL. `name` is a single Jira display name / username."""
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
    if value is None:
        return out
    if isinstance(value, bool):
        return out
    if isinstance(value, (int, float)):
        out.append(int(value))
    elif isinstance(value, str):
        for token in value.replace(",", " ").split():
            token = token.strip()
            if token.isdigit():
                out.append(int(token))
    elif isinstance(value, dict):
        out.extend(_extract_ids(value.get("value")))
        out.extend(_extract_ids(value.get("name")))
    elif isinstance(value, list):
        for item in value:
            out.extend(_extract_ids(item))
    return out


class JiraClient:
    def __init__(self, base_url: str, cookie: str, spotid_field: str, verify: bool = True):
        self.base_url = base_url.rstrip("/")
        self.spotid_field = spotid_field
        self.session = requests.Session()
        self.session.headers.update({
            "Cookie": cookie,
            "Accept": "application/json",
        })
        self.session.verify = verify  # set False if internal Jira uses a self-signed cert

    def find_field_id(self, field_name: str):
        """Helper to discover the SpotID custom field id (run once, then hardcode it).
        Returns matching fields like [{'id': 'customfield_12345', 'name': 'SpotID'}, ...]."""
        resp = self.session.get(f"{self.base_url}/rest/api/2/field")
        resp.raise_for_status()
        return [f for f in resp.json() if field_name.lower() in f.get("name", "").lower()]

    def search_issues(self, jql: str, page_size: int = 100) -> Iterator[dict]:
        """Yield every issue matching the JQL, following pagination."""
        start_at = 0
        while True:
            resp = self.session.get(
                f"{self.base_url}/rest/api/2/search",
                params={
                    "jql": jql,
                    "startAt": start_at,
                    "maxResults": page_size,
                    "fields": self.spotid_field,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            issues = data.get("issues", [])
            for issue in issues:
                yield issue
            start_at += len(issues)
            if not issues or start_at >= data.get("total", 0):
                break

    def spot_ids_for_name(self, name: str, time_range: str) -> Set[int]:
        ids: Set[int] = set()
        for issue in self.search_issues(build_jql(name, time_range)):
            value = issue.get("fields", {}).get(self.spotid_field)
            ids.update(_extract_ids(value))
        return ids

    def spot_ids_for_names(self, names: Iterable[str], time_range: str) -> Set[int]:
        all_ids: Set[int] = set()
        for name in names:
            found = self.spot_ids_for_name(name, time_range)
            print(f"  {name}: {len(found)} spot id(s)")
            all_ids.update(found)
        return all_ids