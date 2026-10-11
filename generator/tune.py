#!/usr/bin/env python3
"""Show how the classifier scores a cached pull — for tuning precision/recall."""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
from collections import Counter

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import classify  # noqa: E402

CACHE = HERE / "raw-cache.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=str(CACHE))
    ap.add_argument("--min", type=float, default=0.0, help="only show score >= this")
    ap.add_argument("--limit", type=int, default=80)
    ap.add_argument("--source", default=None, help="filter to one source")
    args = ap.parse_args()

    data = json.loads(pathlib.Path(args.cache).read_text())
    rows = []
    for e in data["events"]:
        if e.get("anchor"):
            continue
        if args.source and args.source not in (e.get("source") or ""):
            continue
        score, matched, topics = classify.score_event(
            e["name"], e.get("url", ""), e.get("description", ""), e.get("tags", []))
        if score < args.min:
            continue
        rows.append((score, e, matched, topics))

    rows.sort(key=lambda r: -r[0])
    passed = sum(1 for r in rows if classify.is_relevant(r[0]))
    print(f"{len(data['events'])} raw events | {len(rows)} scoring >= {args.min} "
          f"| {passed} would PASS (threshold {classify.RELEVANCE_THRESHOLD})\n")
    for score, e, matched, topics in rows[:args.limit]:
        flag = "PASS" if classify.is_relevant(score) else "    "
        print(f"{flag} {score:6.1f} | {e['name'][:62]:62} | {e.get('source','')[:14]:14} "
              f"| {','.join(matched[:5])[:70]}")

    # how close are the near-misses? tells us if the threshold is badly placed
    near = [r for r in rows if 2 <= r[0] < classify.RELEVANCE_THRESHOLD]
    print(f"\n{len(near)} events scored 2..threshold (near misses)")
    print("score histogram:", Counter(round(r[0]) for r in rows).most_common(14))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
