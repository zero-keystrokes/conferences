#!/usr/bin/env python3
"""Build the Streaming & Data Events page.

Usage:
    python3 build.py                  # build into ../site
    python3 build.py --out DIR        # build elsewhere
    python3 build.py --no-anchor-refresh
    python3 build.py --publish        # build, then git commit + push
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import classify          # noqa: E402
import render            # noqa: E402
import sources           # noqa: E402
from model import merge_events, to_iso   # noqa: E402

WINDOW_DAYS = 92        # "next 3 months"
BEYOND_DAYS = 400       # how far out the "further out" section reaches


def build(out_dir: pathlib.Path, refresh_anchors: bool = True,
          window_days: int = WINDOW_DAYS, beyond_days: int = BEYOND_DAYS) -> dict:
    today = dt.date.today()
    window_start = today
    window_end = today + dt.timedelta(days=window_days)
    horizon_end = today + dt.timedelta(days=beyond_days)

    sources.WARNINGS.clear()
    print("Collecting…")
    raw = sources.collect_all(today, refresh_anchors=refresh_anchors)
    print(f"  raw total: {len(raw)}")

    # relevance scoring
    kept = []
    for ev in raw:
        if ev.anchor:
            kept.append(ev)
            continue
        score, matched, topics = classify.score_event(
            ev.name, ev.url, ev.description, ev.tags)
        if not classify.is_relevant(score):
            continue
        ev.score = score
        ev.matched = matched
        # merge classifier topics with source-provided ones, classifier first
        ev.tags = [t for t in topics if t not in ev.tags] + ev.tags
        kept.append(ev)
    print(f"  relevant:  {len(kept)}")

    merged = merge_events(kept)
    print(f"  deduped:   {len(merged)}")

    # keep anything in the window, undated anchors, or inside the far horizon
    events = [ev for ev in merged
              if (ev.start is None and ev.anchor)
              or (ev.start is not None and ev.start <= horizon_end)]
    events.sort(key=lambda e: (e.start is None, e.start or today, e.name.lower()))

    meta = {
        "today": today,
        "window_start": window_start,
        "window_end": window_end,
        "horizon_end": horizon_end,
        "generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M %Z").strip(),
        "next_run": "tonight (see the nightly job)",
        "sources": [
            "developers.events — open conference + CFP feed",
            "tech-conferences/conference-data — per-topic conference JSON",
            "meetup.com — meetup search, schema.org Event data",
            "curated flagship list (generator/anchors.json)",
        ],
        "warnings": list(sources.WARNINGS),
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.html").write_text(render.render(events, meta), encoding="utf-8")
    (out_dir / "events.json").write_text(
        json.dumps({
            "generated_at": meta["generated_at"],
            "window_start": to_iso(window_start),
            "window_end": to_iso(window_end),
            "count": len(events),
            "warnings": meta["warnings"],
            "events": [e.to_dict() for e in events],
        }, indent=2, default=str), encoding="utf-8")
    # Pages: stop Jekyll from eating files that start with an underscore
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")

    in_win = sum(1 for e in events if e.start and window_start <= e.start <= window_end)
    print(f"Built {out_dir/'index.html'} — {len(events)} events "
          f"({in_win} in the 3-month window)")
    if sources.WARNINGS:
        print(f"  {len(sources.WARNINGS)} source warning(s)")
    return {"events": len(events), "in_window": in_win, "warnings": list(sources.WARNINGS)}


def publish(repo: pathlib.Path, message: str | None = None) -> None:
    """Commit and push the regenerated page."""
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    diff = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=repo)
    if diff.returncode == 0:
        print("No changes to publish.")
        return
    msg = message or f"chore: nightly refresh {dt.date.today().isoformat()}"
    subprocess.run(["git", "commit", "-m", msg], cwd=repo, check=True)
    subprocess.run(["git", "push"], cwd=repo, check=True)
    print(f"Published: {msg}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HERE.parent / "docs"))
    ap.add_argument("--window-days", type=int, default=WINDOW_DAYS)
    ap.add_argument("--beyond-days", type=int, default=BEYOND_DAYS)
    ap.add_argument("--no-anchor-refresh", action="store_true")
    ap.add_argument("--publish", action="store_true")
    ap.add_argument("--message", default=None)
    args = ap.parse_args()

    out_dir = pathlib.Path(args.out).resolve()
    result = build(out_dir, refresh_anchors=not args.no_anchor_refresh,
                   window_days=args.window_days, beyond_days=args.beyond_days)
    if args.publish:
        publish(out_dir.parent, args.message)
    return 0 if result["events"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
