"""Render a View as a self-contained HTML dashboard and a flat CSV."""

from __future__ import annotations

import csv
from datetime import datetime
from html import escape
from pathlib import Path

from .tracker import Thread, View

SOURCE_LABEL = {"jira": "Jira", "slack": "Slack", "confluence": "Confluence", "sheets": "Sheet"}


def write_csv(view: View, path: str | Path) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["thread", "source", "kind", "title", "customer", "owner", "reporter",
                    "status", "updated", "url"])
        for t in sorted(view.threads, key=lambda t: t.key):
            for i in t.items:
                w.writerow([t.key, i.source, i.kind, i.title, i.customer, i.owner, i.reporter,
                            i.status, i.updated.date().isoformat(), i.url])


def write_html(view: View, path: str | Path, title: str = "Product requirements tracker") -> None:
    Path(path).write_text(render_html(view, title), encoding="utf-8")


def render_html(view: View, title: str) -> str:
    stats = [
        ("Open threads", len(view.open), ""),
        ("Launch blockers", len(view.blockers), "alert" if view.blockers else ""),
        ("Feedback with no ticket", len(view.untriaged), "warn" if view.untriaged else ""),
        (f"No update in {view.stale_days}+ days", len(view.stale), "warn" if view.stale else ""),
    ]
    tiles = "".join(
        f'<div class="tile {cls}"><div class="num">{n}</div><div class="lbl">{escape(label)}</div></div>'
        for label, n, cls in stats
    )

    customers = "".join(
        f'<section class="cust"><h3>{escape(name)} <span class="count">{len(ts)}</span></h3>'
        f'<ul>{"".join(f"<li>{_title(t)}</li>" for t in ts)}</ul></section>'
        for name, ts in view.by_customer().items()
    )
    owners = "".join(
        f"<tr><td>{escape(o)}</td><td class='n'>{n}</td></tr>" for o, n in view.by_owner().items()
    )

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<style>{CSS}</style></head>
<body><main>
<header><h1>{escape(title)}</h1>
<p class="asof">As of {view.as_of:%b %d, %Y} · built from {_source_summary(view)}</p></header>
<div class="tiles">{tiles}</div>

<h2>Launch blockers</h2>
{_table(view.blockers, view, "No open blockers.")}

<h2>Customer feedback with no ticket</h2>
<p class="hint">Mentioned in Slack or the request log, but nobody has filed it yet.</p>
{_table(view.untriaged, view, "Everything has a ticket.")}

<h2>By customer</h2>
<div class="custs">{customers or "<p class='empty'>Nothing open.</p>"}</div>

<h2>Open items by owner</h2>
<div class="tbl owners"><table><thead><tr><th>Owner</th><th class="n">Open</th></tr></thead><tbody>{owners}</tbody></table></div>

<h2>Gone quiet</h2>
<p class="hint">Open, with no activity in any source for {view.stale_days}+ days.</p>
{_table(view.stale, view, "Nothing stale.")}
</main></body></html>
"""


def _source_summary(view: View) -> str:
    # An item linked to two tickets appears in two threads; count it once.
    unique = {i.uid: i.source for t in view.threads for i in t.items}
    counts: dict[str, int] = {}
    for source in unique.values():
        counts[source] = counts.get(source, 0) + 1
    return ", ".join(f"{n} {SOURCE_LABEL.get(s, s)} items" for s, n in sorted(counts.items()))


def _title(t: Thread) -> str:
    return f'<a href="{escape(t.anchor.url)}">{escape(t.anchor.title)}</a>'


def _table(threads: list[Thread], view: View, empty: str) -> str:
    if not threads:
        return f'<p class="empty">{escape(empty)}</p>'
    rows = []
    for t in threads:
        links = " ".join(
            f'<a class="src {i.source}" href="{escape(i.url)}" title="{escape(i.title)}">'
            f"{SOURCE_LABEL.get(i.source, i.source)}</a>"
            for i in t.items
        )
        raised = "" if t.has_ticket or not t.anchor.reporter else (
            f"<span class='by'>raised by {escape(t.anchor.reporter)}</span>")
        rows.append(
            "<tr>"
            f"<td>{_title(t)}<div class='srcs'>{links}{raised}</div></td>"
            f"<td>{escape(', '.join(t.customers)) or '—'}</td>"
            f"<td>{escape(t.anchor.owner) or '—'}</td>"
            f"<td>{escape(t.anchor.status) if t.has_ticket else 'no ticket'}</td>"
            f"<td class='n'>{_age(t.updated, view.as_of)}</td>"
            "</tr>"
        )
    return (
        "<div class='tbl'><table><thead><tr><th>Item</th><th>Customer</th><th>Owner</th>"
        "<th>Status</th><th class='n'>Last activity</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def _age(updated: datetime, as_of: datetime) -> str:
    days = (as_of - updated).days
    return "today" if days <= 0 else f"{days}d ago"


CSS = """
:root{--bg:#fafaf9;--fg:#1c1917;--muted:#78716c;--line:#e7e5e4;--card:#fff;
--alert:#b91c1c;--alert-bg:#fef2f2;--warn:#a16207;--warn-bg:#fefce8;--link:#1d4ed8}
@media (prefers-color-scheme:dark){:root{--bg:#1c1917;--fg:#f5f5f4;--muted:#a8a29e;
--line:#44403c;--card:#292524;--alert:#fca5a5;--alert-bg:#3b1515;--warn:#fde68a;
--warn-bg:#3a2f0b;--link:#93c5fd}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
main{max-width:1040px;margin:0 auto;padding:32px 16px 64px}
h1{font-size:26px;margin:0}h2{font-size:18px;margin:40px 0 8px}h3{font-size:15px;margin:0 0 6px}
.asof,.hint,.empty{color:var(--muted);margin:4px 0 12px}a{color:var(--link);text-decoration:none}
a:hover{text-decoration:underline}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-top:24px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px}
.tile .num{font-size:30px;font-weight:650;font-variant-numeric:tabular-nums}
.tile .lbl{color:var(--muted);font-size:13px}
.tile.alert{background:var(--alert-bg);border-color:transparent}.tile.alert .num{color:var(--alert)}
.tile.warn{background:var(--warn-bg);border-color:transparent}.tile.warn .num{color:var(--warn)}
.tbl{background:var(--card);border:1px solid var(--line);border-radius:10px;overflow-x:auto}
table{width:100%;border-collapse:collapse}
td:first-child{min-width:260px}
th,td{text-align:left;padding:10px 12px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);font-weight:600}
tr:last-child td{border-bottom:0}.n{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
.owners{max-width:420px}
.srcs{margin-top:4px;display:flex;gap:6px;flex-wrap:wrap}
.src{font-size:11px;padding:1px 7px;border-radius:999px;border:1px solid var(--line);color:var(--muted)}
.custs{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px}
.cust{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.cust ul{margin:0;padding-left:18px}.cust li{margin:3px 0}
.count{color:var(--muted);font-weight:400}.by{font-size:12px;color:var(--muted)}
"""
