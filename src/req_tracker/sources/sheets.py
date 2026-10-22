"""Google Sheets: the customer-request log many teams keep on the side.

Reads one range with the Sheets v4 values API. The first row is treated
as headers; column names are mapped in config, so any sheet layout works.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import requests

from ..config import Config
from ..models import FEEDBACK, Item, find_jira_keys

DEFAULT_COLUMNS = {
    "date": "Date", "customer": "Customer", "request": "Request",
    "owner": "Owner", "status": "Status", "jira": "Jira", "reporter": "Requested by",
}


def fetch(cfg: Config) -> dict:
    sheet_id = cfg.sheets["spreadsheet_id"]
    rng = cfg.sheets.get("range", "Requests!A1:Z")
    token = os.environ[cfg.sheets.get("token_env", "GOOGLE_ACCESS_TOKEN")]
    resp = requests.get(
        f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}/values/{rng}",
        headers={"Authorization": f"Bearer {token}"},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def parse(payload: dict, cfg: Config) -> list[Item]:
    rows = payload.get("values", [])
    if not rows:
        return []
    columns = {**DEFAULT_COLUMNS, **cfg.sheets.get("columns", {})}
    header = [h.strip() for h in rows[0]]
    index = {key: header.index(name) for key, name in columns.items() if name in header}
    for required in ("date", "request"):
        if required not in index:
            raise ValueError(f"sheet is missing the '{columns[required]}' column")

    sheet_url = f"https://docs.google.com/spreadsheets/d/{cfg.sheets.get('spreadsheet_id', '')}"
    items = []
    for n, row in enumerate(rows[1:], start=2):
        def cell(key: str) -> str:
            i = index.get(key)
            return row[i].strip() if i is not None and i < len(row) else ""

        request = cell("request")
        if not request:
            continue
        customer_text = cell("customer")
        items.append(Item(
            source="sheets",
            source_id=f"row-{n}",
            kind=FEEDBACK,
            title=request,
            url=f"{sheet_url}#gid=0&range=A{n}",
            updated=_parse_date(cell("date")),
            customer=cfg.customer_in(customer_text) or customer_text,
            owner=cell("owner"),
            reporter=cell("reporter"),
            status=cell("status") or "open",
            jira_keys=find_jira_keys(f"{cell('jira')} {request}", cfg.jira_projects),
        ))
    return items


def _parse_date(value: str) -> datetime:
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"unrecognized date '{value}' (expected YYYY-MM-DD or MM/DD/YYYY)")
