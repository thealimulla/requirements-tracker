"""Slack: customer feedback and launch blockers from channel messages.

Live mode calls conversations.history for each configured channel. Most
channel chatter is noise, so a message becomes an item only if it reads
as a blocker or as customer feedback, or if it references a Jira issue.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import requests

from ..config import Config
from ..models import BLOCKER, FEEDBACK, Item, find_jira_keys

API = "https://slack.com/api/conversations.history"
BLOCKER_REACTIONS = {"rotating_light", "no_entry", "octagonal_sign"}


def fetch(cfg: Config) -> list[dict]:
    """Return raw messages, each tagged with its channel id."""
    token = os.environ[cfg.slack.get("token_env", "SLACK_TOKEN")]
    headers = {"Authorization": f"Bearer {token}"}
    oldest = cfg.slack.get("oldest", "0")
    messages: list[dict] = []
    for channel in cfg.slack.get("channels", []):
        cursor = None
        while True:
            params = {"channel": channel, "oldest": oldest, "limit": 200}
            if cursor:
                params["cursor"] = cursor
            data = requests.get(API, headers=headers, params=params, timeout=20).json()
            if not data.get("ok"):
                raise RuntimeError(f"Slack error for {channel}: {data.get('error')}")
            messages += [{**m, "channel": channel} for m in data.get("messages", [])]
            cursor = data.get("response_metadata", {}).get("next_cursor")
            if not data.get("has_more") or not cursor:
                break
    return messages


def parse(messages: list[dict], cfg: Config) -> list[Item]:
    workspace = cfg.slack.get("workspace", "")
    users = cfg.slack.get("users", {})
    items = []
    for m in messages:
        if m.get("subtype"):  # joins, bot noise, edits
            continue
        text = m.get("text", "")
        lowered = text.lower()
        reactions = {r.get("name") for r in m.get("reactions", [])}
        keys = find_jira_keys(text, cfg.jira_projects)

        if reactions & BLOCKER_REACTIONS or any(w in lowered for w in cfg.blocker_words):
            kind = BLOCKER
        elif any(w in lowered for w in cfg.feedback_words):
            kind = FEEDBACK
        elif keys:
            kind = FEEDBACK
        else:
            continue

        ts = m["ts"]
        items.append(Item(
            source="slack",
            source_id=f"{m['channel']}/{ts}",
            kind=kind,
            title=_first_line(text),
            url=_permalink(workspace, m["channel"], ts),
            updated=datetime.fromtimestamp(float(ts), tz=timezone.utc),
            customer=cfg.customer_in(text),
            reporter=users.get(m.get("user", ""), m.get("user", "")),
            status="open",
            jira_keys=keys,
        ))
    return items


def _permalink(workspace: str, channel: str, ts: str) -> str:
    # Slack's documented permalink format: /archives/<channel>/p<ts without the dot>
    return f"https://{workspace}.slack.com/archives/{channel}/p{ts.replace('.', '')}"


def _first_line(text: str, limit: int = 140) -> str:
    line = text.strip().splitlines()[0] if text.strip() else ""
    return line if len(line) <= limit else line[: limit - 1] + "…"
