from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .config import load_config
from .report import write_csv, write_html
from .sources import ALL
from .tracker import build_view

SAMPLE_LIST_KEY = {"slack": "messages", "jira": "issues", "confluence": "results"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="req-tracker",
        description="One view of product requirements across Slack, Jira, Confluence and Sheets.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="pull from every source and write the dashboard")
    build.add_argument("--config", required=True, help="path to tracker.toml")
    build.add_argument("--out", default="dist", help="output folder (default: dist)")
    build.add_argument("--sample", metavar="DIR",
                       help="read saved API responses from DIR instead of calling the APIs")
    build.add_argument("--as-of", help="report date, YYYY-MM-DD (default: now)")

    args = parser.parse_args(argv)
    cfg = load_config(args.config)
    as_of = (datetime.fromisoformat(args.as_of).replace(tzinfo=timezone.utc)
             if args.as_of else datetime.now(timezone.utc))

    items = []
    for name, module in ALL.items():
        if args.sample:
            path = Path(args.sample) / f"{name}.json"
            if not path.exists():
                continue
            raw = json.loads(path.read_text())
            # Saved files hold the API's own response shape; unwrap the list.
            if name in SAMPLE_LIST_KEY:
                raw = raw[SAMPLE_LIST_KEY[name]]
        else:
            if not getattr(cfg, name):
                continue
            try:
                raw = module.fetch(cfg)
            except KeyError as e:
                print(f"error: {name} needs the environment variable or setting {e}",
                      file=sys.stderr)
                return 2
        parsed = module.parse(raw, cfg)
        print(f"{name:<11} {len(parsed):>4} items")
        items += parsed

    view = build_view(items, as_of, cfg.stale_days)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    write_html(view, out / "index.html")
    write_csv(view, out / "items.csv")
    print(f"\n{len(view.open)} open threads, {len(view.blockers)} blockers, "
          f"{len(view.untriaged)} untriaged, {len(view.stale)} stale")
    print(f"wrote {out / 'index.html'} and {out / 'items.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
