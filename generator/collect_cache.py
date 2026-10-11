#!/usr/bin/env python3
"""Collect all sources once and cache the raw pull to JSON, so classifier and
render tuning can iterate instantly without re-hitting the network."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import sources  # noqa: E402
from model import to_iso  # noqa: E402

CACHE = HERE / "raw-cache.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(CACHE))
    ap.add_argument("--no-anchor-refresh", action="store_true")
    args = ap.parse_args()

    today = dt.date.today()
    events = sources.collect_all(today, refresh_anchors=not args.no_anchor_refresh)

    payload = {
        "collected_at": dt.datetime.now().isoformat(timespec="seconds"),
        "today": to_iso(today),
        "warnings": list(sources.WARNINGS),
        "events": [
            {
                "name": e.name, "url": e.url,
                "start": to_iso(e.start), "end": to_iso(e.end),
                "city": e.city, "country": e.country, "online": e.online,
                "kind": e.kind, "source": e.source, "source_url": e.source_url,
                "cfp_url": e.cfp_url, "cfp_close": to_iso(e.cfp_close),
                "cfp_open": to_iso(e.cfp_open), "cfp_note": e.cfp_note,
                "description": e.description, "tags": e.tags,
                "verified": e.verified, "anchor": e.anchor,
            }
            for e in events
        ],
    }
    pathlib.Path(args.out).write_text(json.dumps(payload, indent=1), encoding="utf-8")
    print(f"cached {len(events)} raw events -> {args.out}")
    if sources.WARNINGS:
        for w in sources.WARNINGS:
            print("  warn:", w)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
