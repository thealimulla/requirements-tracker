"""Tracker configuration, loaded from a TOML file.

Secrets never live in the config file: each source names the environment
variable that holds its token.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Customer:
    name: str
    aliases: list[str]      # words that identify this customer in free text
    jira_label: str = ""    # e.g. "customer-acme"


@dataclass
class Config:
    customers: list[Customer]
    jira_projects: set[str] = field(default_factory=set)
    stale_days: int = 14
    blocker_words: list[str] = field(default_factory=lambda: [
        "blocker", "blocking", "blocked", "can't launch", "cannot launch", "launch risk",
    ])
    feedback_words: list[str] = field(default_factory=lambda: [
        "asked for", "asking for", "requested", "would like", "wants",
        "feedback", "complained", "frustrated", "missing",
    ])
    slack: dict = field(default_factory=dict)
    jira: dict = field(default_factory=dict)
    confluence: dict = field(default_factory=dict)
    sheets: dict = field(default_factory=dict)

    def customer_in(self, text: str) -> str:
        """Return the first configured customer mentioned in text, or ''."""
        lowered = (text or "").lower()
        for c in self.customers:
            if any(alias.lower() in lowered for alias in [c.name, *c.aliases]):
                return c.name
        return ""

    def customer_for_label(self, labels: list[str]) -> str:
        for c in self.customers:
            if c.jira_label and c.jira_label in labels:
                return c.name
        return ""


def load_config(path: str | Path) -> Config:
    with open(path, "rb") as f:
        data = tomllib.load(f)
    customers = [
        Customer(name=c["name"], aliases=c.get("aliases", []), jira_label=c.get("jira_label", ""))
        for c in data.get("customers", [])
    ]
    tracker = data.get("tracker", {})
    cfg = Config(
        customers=customers,
        jira_projects=set(tracker.get("jira_projects", [])),
        stale_days=tracker.get("stale_days", 14),
        slack=data.get("slack", {}),
        jira=data.get("jira", {}),
        confluence=data.get("confluence", {}),
        sheets=data.get("sheets", {}),
    )
    if "blocker_words" in tracker:
        cfg.blocker_words = tracker["blocker_words"]
    if "feedback_words" in tracker:
        cfg.feedback_words = tracker["feedback_words"]
    return cfg
