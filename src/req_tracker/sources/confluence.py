"""Confluence Cloud: requirements docs and specs.

Uses CQL content search (/wiki/rest/api/content/search) and expands the
page body so Jira keys mentioned anywhere on the page can be linked.
"""

from __future__ import annotations

import os
from datetime import datetime

import requests

from ..config import Config
from ..models import SPEC, Item, find_jira_keys


def fetch(cfg: Config) -> list[dict]:
    site = cfg.confluence["site"].rstrip("/")
    auth = (os.environ[cfg.confluence.get("email_env", "JIRA_EMAIL")],
            os.environ[cfg.confluence.get("token_env", "JIRA_TOKEN")])
    url = f"{site}/wiki/rest/api/content/search"
    params: dict | None = {
        "cql": cfg.confluence["cql"],
        "expand": "version,body.storage",
        "limit": 50,
    }
    pages: list[dict] = []
    while url:
        resp = requests.get(url, params=params, auth=auth, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        pages += data.get("results", [])
        nxt = data.get("_links", {}).get("next")
        url = f"{data['_links']['base']}{nxt}" if nxt else ""
        params = None  # the next link already carries the query
    return pages


def parse(pages: list[dict], cfg: Config) -> list[Item]:
    site = cfg.confluence.get("site", "").rstrip("/")
    items = []
    for page in pages:
        body = (page.get("body", {}).get("storage", {}) or {}).get("value", "")
        title = page.get("title", "")
        version = page.get("version", {})
        items.append(Item(
            source="confluence",
            source_id=str(page["id"]),
            kind=SPEC,
            title=title,
            url=f"{site}/wiki{page.get('_links', {}).get('webui', '')}",
            updated=datetime.fromisoformat(version["when"]),
            customer=cfg.customer_in(title),
            owner=(version.get("by") or {}).get("displayName", ""),
            # A spec isn't work in itself: it shows up under the tickets it
            # mentions, and doesn't count as an open item on its own.
            status="published",
            jira_keys=find_jira_keys(f"{title} {body}", cfg.jira_projects),
        ))
    return items
