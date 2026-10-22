from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from req_tracker.models import BLOCKER, FEEDBACK, SPEC, WORK, find_jira_keys
from req_tracker.sources import confluence, jira, sheets, slack


def test_find_jira_keys_filters_projects():
    text = "See REL-101 and OPS-9, not COVID-19 or lowercase rel-5"
    assert find_jira_keys(text) == {"REL-101", "OPS-9", "COVID-19"}
    assert find_jira_keys(text, {"REL"}) == {"REL-101"}


# -- Slack ------------------------------------------------------------------

def test_slack_classifies_and_drops_noise(cfg, sample):
    items = {i.source_id: i for i in slack.parse(sample("slack")["messages"], cfg)}
    assert len(items) == 6  # lunch chatter and the channel join are dropped

    sso = items["C02LAUNCH/1792418700.000100"]
    assert sso.kind == BLOCKER
    assert sso.customer == "Brightline Health"
    assert sso.reporter == "Priya Raman"
    assert sso.owner == ""
    assert sso.jira_keys == {"REL-101"}
    assert sso.url == "https://relay-demo.slack.com/archives/C02LAUNCH/p1792418700000100"
    assert sso.updated == datetime(2026, 10, 19, 14, 5, 0, 100, tzinfo=timezone.utc)

    assert items["C02LAUNCH/1790947800.000500"].kind == BLOCKER        # "can't launch"
    assert items["C01FEEDBACK/1792145520.000300"].kind == FEEDBACK     # "would like"
    assert items["C01FEEDBACK/1792238400.000600"].kind == FEEDBACK     # mentions a ticket


def test_slack_blocker_reaction_alone_marks_blocker(cfg):
    msg = {"channel": "C1", "ts": "1792418700.1", "user": "U9", "text": "hmm, look at this",
           "reactions": [{"name": "rotating_light", "count": 1}]}
    assert slack.parse([msg], cfg)[0].kind == BLOCKER


def test_slack_fetch_pages_with_cursor(cfg, monkeypatch):
    cfg.slack["channels"] = ["C1"]
    monkeypatch.setenv("SLACK_TOKEN", "xoxb-test")
    pages = [
        {"ok": True, "messages": [{"ts": "1"}], "has_more": True,
         "response_metadata": {"next_cursor": "abc"}},
        {"ok": True, "messages": [{"ts": "2"}], "has_more": False},
    ]
    get = MagicMock(side_effect=[MagicMock(json=MagicMock(return_value=p)) for p in pages])
    monkeypatch.setattr(slack.requests, "get", get)

    msgs = slack.fetch(cfg)
    assert [m["ts"] for m in msgs] == ["1", "2"]
    assert all(m["channel"] == "C1" for m in msgs)
    assert get.call_args_list[1].kwargs["params"]["cursor"] == "abc"


def test_slack_fetch_surfaces_api_errors(cfg, monkeypatch):
    cfg.slack["channels"] = ["C1"]
    monkeypatch.setenv("SLACK_TOKEN", "x")
    resp = MagicMock(json=MagicMock(return_value={"ok": False, "error": "not_in_channel"}))
    monkeypatch.setattr(slack.requests, "get", MagicMock(return_value=resp))
    with pytest.raises(RuntimeError, match="not_in_channel"):
        slack.fetch(cfg)


# -- Jira -------------------------------------------------------------------

def test_jira_parse(cfg, sample):
    items = {i.source_id: i for i in jira.parse(sample("jira")["issues"], cfg)}
    assert items["REL-101"].kind == BLOCKER          # label + Highest priority
    assert items["REL-112"].kind == BLOCKER          # label only
    assert items["REL-110"].kind == WORK
    assert items["REL-112"].owner == ""               # unassigned
    assert items["REL-104"].customer == "Acme Logistics"
    assert items["REL-120"].customer == ""
    assert items["REL-101"].url == "https://relay-demo.atlassian.net/browse/REL-101"
    assert items["REL-115"].is_open is False


@pytest.mark.parametrize("raw, expected", [
    ("2026-10-19T15:02:11.000+0000", datetime(2026, 10, 19, 15, 2, 11, tzinfo=timezone.utc)),
    ("2026-10-19T15:02:11.000-0500", datetime(2026, 10, 19, 20, 2, 11, tzinfo=timezone.utc)),
    ("2026-10-19T15:02:11.000+00:00", datetime(2026, 10, 19, 15, 2, 11, tzinfo=timezone.utc)),
])
def test_jira_time_formats(raw, expected):
    assert jira._parse_jira_time(raw) == expected


def test_jira_fetch_follows_next_page_token(cfg, monkeypatch):
    monkeypatch.setenv("JIRA_EMAIL", "me@example.com")
    monkeypatch.setenv("JIRA_TOKEN", "t")
    pages = [{"issues": [{"key": "REL-1"}], "nextPageToken": "p2"}, {"issues": [{"key": "REL-2"}]}]
    sent_bodies = []

    def post(url, json, **kw):
        assert url.endswith("/rest/api/3/search/jql")
        sent_bodies.append(dict(json))
        return MagicMock(json=MagicMock(return_value=pages[len(sent_bodies) - 1]))

    monkeypatch.setattr(jira.requests, "post", post)
    assert [i["key"] for i in jira.fetch(cfg)] == ["REL-1", "REL-2"]
    assert "nextPageToken" not in sent_bodies[0]
    assert sent_bodies[1]["nextPageToken"] == "p2"


# -- Confluence ---------------------------------------------------------------

def test_confluence_parse_links_keys_from_body(cfg, sample):
    items = {i.source_id: i for i in confluence.parse(sample("confluence")["results"], cfg)}
    launch = items["884736"]
    assert launch.kind == SPEC
    assert launch.jira_keys == {"REL-101", "REL-112"}
    assert launch.customer == "Brightline Health"
    assert launch.owner == "Priya Raman"
    assert launch.url.startswith("https://relay-demo.atlassian.net/wiki/spaces/PROD/pages/884736")
    assert launch.is_open is False  # a spec on its own isn't open work


def test_confluence_fetch_follows_next_link(cfg, monkeypatch):
    monkeypatch.setenv("JIRA_EMAIL", "me@example.com")
    monkeypatch.setenv("JIRA_TOKEN", "t")
    base = "https://relay-demo.atlassian.net/wiki"
    pages = [
        {"results": [{"id": "1"}], "_links": {"base": base, "next": "/rest/api/content/search?cursor=x"}},
        {"results": [{"id": "2"}], "_links": {"base": base}},
    ]
    calls = []

    def get(url, params=None, **kw):
        calls.append((url, params))
        return MagicMock(json=MagicMock(return_value=pages[len(calls) - 1]))

    monkeypatch.setattr(confluence.requests, "get", get)
    assert [p["id"] for p in confluence.fetch(cfg)] == ["1", "2"]
    assert calls[1] == (f"{base}/rest/api/content/search?cursor=x", None)


# -- Sheets -------------------------------------------------------------------

def test_sheets_parse(cfg, sample):
    items = sheets.parse(sample("sheets"), cfg)
    assert len(items) == 4
    spanish = next(i for i in items if "Spanish" in i.title)
    assert spanish.customer == "Acme Logistics"
    assert spanish.jira_keys == set()
    assert spanish.reporter == "Account manager"
    assert spanish.source_id == "row-3"
    assert next(i for i in items if "duplicate" in i.title).jira_keys == {"REL-115"}


def test_sheets_handles_short_rows_and_custom_columns(cfg):
    cfg.sheets["columns"] = {"date": "When", "request": "Ask"}
    payload = {"values": [["When", "Ask", "Customer"], ["10/03/2026", "Dark mode"], ["2026-10-04", ""]]}
    items = sheets.parse(payload, cfg)
    assert len(items) == 1                      # blank request rows are skipped
    assert items[0].customer == ""              # short row: missing cell, no crash
    assert items[0].updated.date().isoformat() == "2026-10-03"


def test_sheets_missing_required_column(cfg):
    with pytest.raises(ValueError, match="'Request' column"):
        sheets.parse({"values": [["Date", "Customer"], ["2026-10-01", "Acme"]]}, cfg)


def test_sheets_bad_date(cfg):
    with pytest.raises(ValueError, match="unrecognized date"):
        sheets.parse({"values": [["Date", "Request"], ["Oct 1", "Thing"]]}, cfg)
