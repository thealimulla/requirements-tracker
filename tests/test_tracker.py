from datetime import datetime, timezone

from req_tracker.cli import main
from req_tracker.report import render_html
from req_tracker.sources import confluence, jira, sheets, slack
from req_tracker.tracker import build_view

AS_OF = datetime(2026, 10, 20, tzinfo=timezone.utc)


def all_items(cfg, sample):
    return (
        slack.parse(sample("slack")["messages"], cfg)
        + jira.parse(sample("jira")["issues"], cfg)
        + confluence.parse(sample("confluence")["results"], cfg)
        + sheets.parse(sample("sheets"), cfg)
    )


def test_threads_group_around_tickets(cfg, sample):
    view = build_view(all_items(cfg, sample), AS_OF, cfg.stale_days)
    threads = {t.key: t for t in view.threads}

    sso = threads["REL-101"]
    assert sorted(i.source for i in sso.items) == ["confluence", "jira", "slack"]

    # REL-118 is labeled for Cobalt in Jira, and Brightline asked for it in the sheet.
    assert threads["REL-118"].customers == ["Brightline Health", "Cobalt Retail"]

    # The launch spec mentions two tickets, so it sits under both.
    spec_threads = [t.key for t in view.threads if any(i.source_id == "884736" for i in t.items)]
    assert sorted(spec_threads) == ["REL-101", "REL-112"]


def test_view_numbers(cfg, sample):
    view = build_view(all_items(cfg, sample), AS_OF, cfg.stale_days)
    assert len(view.threads) == 10                      # 7 tickets + 3 untriaged
    assert len(view.open) == 9                          # REL-115 is Done
    assert [t.key for t in view.blockers] == ["REL-112", "REL-101"]
    assert len(view.untriaged) == 3
    assert [t.anchor.title[:7] for t in view.stale] == ["REL-104", "Acme op"]
    assert view.by_owner()["(unassigned)"] == 4
    assert list(view.by_customer())[-1] == "(no customer)"


def test_ticket_status_beats_open_chatter(cfg, sample):
    """A Slack thread about a ticket that's Done shouldn't keep it open."""
    view = build_view(all_items(cfg, sample), AS_OF, cfg.stale_days)
    rel115 = next(t for t in view.threads if t.key == "REL-115")
    assert rel115.related                                # the sheet row is attached
    assert rel115.is_open is False


def test_ticket_inherits_customer_from_conversation(cfg):
    from req_tracker.models import FEEDBACK, WORK, Item
    ticket = Item("jira", "REL-9", WORK, "REL-9: thing", "u", AS_OF, status="To Do", jira_keys={"REL-9"})
    chat = Item("slack", "C/1", FEEDBACK, "Acme wants REL-9", "u", AS_OF,
                customer="Acme Logistics", status="open", jira_keys={"REL-9"})
    view = build_view([ticket, chat], AS_OF, 14)
    assert view.threads[0].anchor.customer == "Acme Logistics"


def test_html_counts_shared_items_once_and_escapes(cfg, sample):
    items = all_items(cfg, sample)
    items[0].title = "<script>alert(1)</script>"
    html = render_html(build_view(items, AS_OF, cfg.stale_days), "Tracker")
    assert "3 Confluence items" in html                  # not 4, though one page sits in 2 threads
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


def test_cli_sample_build(tmp_path, capsys):
    code = main([
        "build", "--config", "examples/tracker.toml", "--sample", "examples/sample_data",
        "--as-of", "2026-10-20", "--out", str(tmp_path),
    ])
    assert code == 0
    assert "9 open threads, 2 blockers, 3 untriaged, 2 stale" in capsys.readouterr().out
    assert (tmp_path / "index.html").exists()
    rows = (tmp_path / "items.csv").read_text().splitlines()
    assert rows[0].startswith("thread,source,kind,title")


def test_cli_live_mode_reports_missing_token(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("SLACK_TOKEN", raising=False)
    code = main(["build", "--config", "examples/tracker.toml", "--out", str(tmp_path)])
    assert code == 2
    assert "SLACK_TOKEN" in capsys.readouterr().err
