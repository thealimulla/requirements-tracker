from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime

# Jira issue keys look like PROJ-123. Requiring a word boundary and an
# uppercase project key keeps "COVID-19" style false positives rare; projects
# can be restricted further in config.
JIRA_KEY_RE = re.compile(r"\b([A-Z][A-Z0-9]{1,9}-\d+)\b")

# What an item is, from the product team's point of view.
BLOCKER = "blocker"      # something stopping a launch
FEEDBACK = "feedback"    # a customer asked for or complained about something
WORK = "work"            # a ticket being worked on
SPEC = "spec"            # a requirements doc

OPEN_STATUSES = {"open", "to do", "in progress", "in review", "blocked", "new", "triage", ""}


@dataclass
class Item:
    source: str            # slack | jira | confluence | sheets
    source_id: str         # unique within the source
    kind: str
    title: str
    url: str
    updated: datetime
    customer: str = ""
    owner: str = ""        # who is responsible for it
    reporter: str = ""     # who raised it (e.g. the person who posted in Slack)
    status: str = ""
    jira_keys: set[str] = field(default_factory=set)

    @property
    def uid(self) -> str:
        return f"{self.source}:{self.source_id}"

    @property
    def is_open(self) -> bool:
        return self.status.strip().lower() in OPEN_STATUSES


def find_jira_keys(text: str, projects: set[str] | None = None) -> set[str]:
    keys = set(JIRA_KEY_RE.findall(text or ""))
    if projects:
        keys = {k for k in keys if k.split("-")[0] in projects}
    return keys
