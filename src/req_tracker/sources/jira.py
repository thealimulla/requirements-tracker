"""Jira Cloud: the tickets work actually happens in.

Uses /rest/api/3/search/jql with nextPageToken paging (the older
/rest/api/3/search endpoint has been removed from Jira Cloud).
"""

from __future__ import annotations

import os
from datetime import datetime

import requests

from ..config import Config
from ..models import BLOCKER, WORK, Item

FIELDS = ["summary", "status", "assignee", "updated", "labels", "priority", "issuetype"]
BLOCKER_PRIORITIES = {"highest", "blocker"}


def fetch(cfg: Config) -> list[dict]:
    site = cfg.jira["site"].rstrip("/")
    auth = (os.environ[cfg.jira.get("email_env", "JIRA_EMAIL")],
            os.environ[cfg.jira.get("token_env", "JIRA_TOKEN")])
    body = {"jql": cfg.jira["jql"], "fields": FIELDS, "maxResults": 100}
    issues: list[dict] = []
    while True:
        resp = requests.post(f"{site}/rest/api/3/search/jql", json=body, auth=auth, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        issues += data.get("issues", [])
        token = data.get("nextPageToken")
        if not token:
            break
        body["nextPageToken"] = token
    return issues


def parse(issues: list[dict], cfg: Config) -> list[Item]:
    site = cfg.jira.get("site", "").rstrip("/")
    blocker_label = cfg.jira.get("blocker_label", "launch-blocker")
    items = []
    for issue in issues:
        f = issue["fields"]
        labels = f.get("labels", [])
        priority = ((f.get("priority") or {}).get("name") or "").lower()
        kind = BLOCKER if blocker_label in labels or priority in BLOCKER_PRIORITIES else WORK
        items.append(Item(
            source="jira",
            source_id=issue["key"],
            kind=kind,
            title=f"{issue['key']}: {f.get('summary', '')}",
            url=f"{site}/browse/{issue['key']}",
            updated=_parse_jira_time(f["updated"]),
            customer=cfg.customer_for_label(labels) or cfg.customer_in(f.get("summary", "")),
            owner=(f.get("assignee") or {}).get("displayName", ""),
            status=(f.get("status") or {}).get("name", ""),
            jira_keys={issue["key"]},
        ))
    return items


def _parse_jira_time(value: str) -> datetime:
    # Jira returns e.g. 2026-10-14T09:12:44.123+0000; fromisoformat needs +00:00.
    if len(value) > 5 and value[-5] in "+-" and value[-3] != ":":
        value = f"{value[:-2]}:{value[-2:]}"
    return datetime.fromisoformat(value)
