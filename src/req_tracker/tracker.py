"""Join items from every source into one view.

Items that reference the same Jira issue are grouped into a thread, with
the Jira ticket as its anchor. That turns "a Slack complaint, a row in the
request log, a spec page and a ticket" into one line the team can act on.
Everything without a ticket stays visible on its own, because feedback
nobody has filed yet is exactly what tends to get lost.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .models import BLOCKER, FEEDBACK, Item


@dataclass
class Thread:
    key: str                   # Jira key, or the item's uid if it has none
    anchor: Item               # the Jira ticket when there is one
    related: list[Item] = field(default_factory=list)

    @property
    def items(self) -> list[Item]:
        return [self.anchor, *self.related]

    @property
    def is_blocker(self) -> bool:
        return any(i.kind == BLOCKER for i in self.items)

    @property
    def is_open(self) -> bool:
        # A ticket's status wins; otherwise any open item keeps the thread open.
        if self.anchor.source == "jira":
            return self.anchor.is_open
        return any(i.is_open for i in self.items)

    @property
    def customers(self) -> list[str]:
        return sorted({i.customer for i in self.items if i.customer})

    @property
    def updated(self) -> datetime:
        return max(i.updated for i in self.items)

    @property
    def has_ticket(self) -> bool:
        return self.anchor.source == "jira"


@dataclass
class View:
    threads: list[Thread]
    as_of: datetime
    stale_days: int

    @property
    def open(self) -> list[Thread]:
        return [t for t in self.threads if t.is_open]

    @property
    def blockers(self) -> list[Thread]:
        return sorted((t for t in self.open if t.is_blocker), key=lambda t: t.updated)

    @property
    def untriaged(self) -> list[Thread]:
        """Open customer feedback with no Jira ticket behind it."""
        return sorted(
            (t for t in self.open if not t.has_ticket and t.anchor.kind == FEEDBACK),
            key=lambda t: t.updated,
        )

    @property
    def stale(self) -> list[Thread]:
        cutoff = self.as_of - timedelta(days=self.stale_days)
        return sorted((t for t in self.open if t.updated < cutoff), key=lambda t: t.updated)

    def by_customer(self) -> dict[str, list[Thread]]:
        out: dict[str, list[Thread]] = defaultdict(list)
        for t in self.open:
            for c in t.customers or ["(no customer)"]:
                out[c].append(t)
        return dict(sorted(out.items(), key=lambda kv: (kv[0] == "(no customer)", -len(kv[1]), kv[0])))

    def by_owner(self) -> dict[str, int]:
        counts: dict[str, int] = defaultdict(int)
        for t in self.open:
            counts[t.anchor.owner or "(unassigned)"] += 1
        return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def build_threads(items: list[Item]) -> list[Thread]:
    tickets = {i.source_id: i for i in items if i.source == "jira"}
    threads: dict[str, Thread] = {k: Thread(k, t) for k, t in tickets.items()}

    for item in items:
        if item.source == "jira":
            continue
        linked = sorted(k for k in item.jira_keys if k in threads)
        if linked:
            # An item that mentions several tickets shows up under each one.
            for k in linked:
                threads[k].related.append(item)
        else:
            threads[item.uid] = Thread(item.uid, item)

    # Customer from the conversation flows to a ticket that lacks one.
    for t in threads.values():
        if not t.anchor.customer:
            names = {i.customer for i in t.related if i.customer}
            if len(names) == 1:
                t.anchor.customer = names.pop()
    return list(threads.values())


def build_view(items: list[Item], as_of: datetime, stale_days: int) -> View:
    return View(build_threads(items), as_of, stale_days)
