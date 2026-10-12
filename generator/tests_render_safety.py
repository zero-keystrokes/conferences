#!/usr/bin/env python3
"""Adversarial checks for the renderer, classifier and date policy.

The page is public and every string on it is scraped from a third party, so
escaping, URL sanitisation and date sanity are load-bearing. These assertions
are the proof; run them before any push.

    python3 tests_render_safety.py
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import re
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import classify          # noqa: E402
import render            # noqa: E402
import sources           # noqa: E402
from model import Event  # noqa: E402

FAILURES: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {label}")
    else:
        FAILURES.append(f"{label} {detail}".strip())
        print(f"  FAIL  {label}  {detail}")


def render_one(ev: Event) -> tuple[str, str, str]:
    """Return (full html, rendered-body html, embedded json text)."""
    today = dt.date.today()
    meta = {
        "today": today,
        "window_start": today,
        "window_end": today + dt.timedelta(days=92),
        "horizon_end": today + dt.timedelta(days=400),
        "generated_at": "test",
        "sources": ["unit-test"],
        "warnings": [],
    }
    ev.start = ev.start or today
    full = render.render([ev], meta)
    body, _, tail = full.partition('id="events-data">')
    json_region = tail.split("</script>", 1)[0]
    return full, body, json_region


def main() -> int:
    print("XSS / escaping (rendered body)")
    hostile = '<script>alert("xss")</script>'
    full, body, json_region = render_one(Event(
        name=hostile, url="https://example.com/ok", cfp_url="javascript:alert(1)",
        cfp_close=dt.date.today() + dt.timedelta(days=10)))
    check("no executable <script> injected into the body",
          "<script>alert" not in body, "raw script tag leaked")
    check("hostile name is entity-escaped", "&lt;script&gt;" in body)
    check("no javascript: href in the body",
          'href="javascript:' not in body.lower())
    check("legit https URL survives", "https://example.com/ok" in body)
    check("external links carry noopener+noreferrer",
          "noopener noreferrer" in body, "missing rel hardening")

    print("\nEmbedded JSON block")
    full2, _, json_region2 = render_one(Event(
        name="</script><script>alert(1)</script>", url="https://ok.example/",
        city='"><img src=x onerror=alert(1)>'))
    check("no literal </script> in the JSON block", "</script>" not in json_region2)
    check("no raw angle brackets in the JSON block", "<" not in json_region2)
    try:
        parsed = json.loads(json_region2)
        check("embedded JSON still parses", True)
    except Exception as exc:  # noqa: BLE001
        parsed = []
        check("embedded JSON still parses", False, str(exc))
    check("escaped payload round-trips to the original text",
          bool(parsed) and parsed[0]["name"] == "</script><script>alert(1)</script>")
    check("hostile cfp/url scheme scrubbed from exported JSON",
          bool(parsed) and not (parsed[0].get("url") or "").lower().startswith("javascript:"))

    print("\nURL scheme allowlist")
    for label, bad in [
        ("data: URL", "data:text/html,<script>alert(1)</script>"),
        ("vbscript:", "vbscript:msgbox(1)"),
        ("protocol-relative", "//evil.example.com/x"),
        ("plain junk", "not a url at all"),
        ("javascript: with case", "JaVaScRiPt:alert(1)"),
    ]:
        _, b, _ = render_one(Event(name="e", url=bad, cfp_url=bad))
        leaked = f'href="{bad}' in b or 'href="javascript:' in b.lower()
        check(f"{label} rejected", not leaked, f"{bad!r} reached an href")
    _, b, _ = render_one(Event(name="e", url="HTTPS://Example.com/x"))
    check("uppercase scheme accepted", "HTTPS://Example.com/x" in b)

    print("\nClassifier precision")
    for name, desc in [("Apache Kafka Summit", ""),
                       ("Flink Forward 2026", "stream processing"),
                       ("Real-Time Data at Scale", "meetup"),
                       ("Lakehouse Day EU", "iceberg and open table formats"),
                       ("Data Engineering Meetup with ClickHouse", "")]:
        score, _, _ = classify.score_event(name, "", desc, [])
        check(f"keeps: {name}", classify.is_relevant(score), f"score={score}")

    for name, desc in [("Data Engineer in 10 Weeks - Job ready Roadmap", ""),
                       ("Let's speak Japanese together", ""),
                       ("Sunrise Yoga in the Park", "data"),
                       ("Navigating Your Career in Tech Bootcamp", "data analytics"),
                       ("Crypto Trading Masterclass", "big data buzzwords")]:
        score, _, _ = classify.score_event(name, "", desc, [])
        check(f"drops: {name}", not classify.is_relevant(score), f"score={score}")

    print("\nClassifier recall (plurals / hyphen variants)")
    for name in ["Open Table Formats in Practice", "Real-time Data Pipelines",
                 "Streaming Analytics Meetup", "Build a Modern Data Stack"]:
        score, _, _ = classify.score_event(name, "", "", [])
        check(f"matches variant: {name}", score > 0, f"score={score}")

    print("\nDate policy (the invariant, not the parser)")
    # The parser may legitimately return an old date found in archive copy; the
    # POLICY is that such a date must never replace a curated one or reach the page.
    tmp = pathlib.Path(tempfile.mkdtemp())
    today = dt.date(2026, 9, 25)

    def run_anchor_case(entry: dict, page: str):
        (tmp / "anchors.json").write_text(json.dumps({"events": [entry]}))
        orig_here, orig_get = sources.HERE, sources.http_get
        sources.HERE = tmp
        sources.http_get = lambda *a, **k: (200, page)
        try:
            return sources.from_anchors(today, refresh=True)[0]
        finally:
            sources.HERE, sources.http_get = orig_here, orig_get

    stale_page = "<title>Some Conf</title><h1>Join us</h1><p>Copyright December 2012.</p>"
    ev = run_anchor_case({"name": "Some Conf", "url": "https://x.example/",
                          "dates": "2027-05-01/2027-05-02", "verified": True}, stale_page)
    check("stale scraped year does not overwrite a curated date",
          ev.start == dt.date(2027, 5, 1), f"got {ev.start}")

    ev = run_anchor_case({"name": "Some Conf", "url": "https://x.example/",
                          "dates": ""}, stale_page)
    check("stale scraped year leaves an unknown date unknown", ev.start is None,
          f"got {ev.start}")

    good_page = "<title>Some Conf 2027</title><h1>March 23-24, 2027</h1>"
    ev = run_anchor_case({"name": "Some Conf", "url": "https://x.example/", "dates": ""},
                         good_page)
    check("genuine future date is accepted",
          ev.start == dt.date(2027, 3, 23) and ev.end == dt.date(2027, 3, 24),
          f"got {ev.start}..{ev.end}")

    past_curated = run_anchor_case(
        {"name": "Old Conf", "url": "https://x.example/", "dates": "2025-01-01/2025-01-02"},
        stale_page)
    check("a past curated date is cleared rather than shown as current",
          past_curated.start is None, f"got {past_curated.start}")

    print("\nDedupe / merge")
    from model import merge_events
    d11 = dt.date(2026, 11, 2)
    a = Event(name="Open Source Analytics Conference", url="https://osacon.io/",
              start=d11, city="San Francisco, CA", source="conference-data")
    b = Event(name="OSA CON 2026: The Anti-Hype Conference for Open Source Analytics",
              url="https://www.meetup.com/x/events/1/", start=d11, source="meetup")
    m = merge_events([a, b])
    check("same event under different names collapses", len(m) == 1, f"got {len(m)}")
    check("richer record wins the url", m and m[0].url == "https://osacon.io/")
    check("city was filled in from the merged record", m and m[0].city == "San Francisco, CA")
    check("source labels union cleanly", m and m[0].source == "conference-data + meetup",
          f"got {m[0].source!r}" if m else "")

    check("distinct same-day events are NOT merged",
          len(merge_events([Event(name="Kafka Summit", url="https://k.example/", start=d11),
                            Event(name="Flink Forward", url="https://f.example/", start=d11)])) == 2)

    same = [Event(name="Big Data Conf", source=s, start=dt.date(2027, 1, 1))
            for s in ("conference-data", "developers.events", "meetup")]
    mm = merge_events(same)
    check("three-way merge yields one record", len(mm) == 1, f"got {len(mm)}")
    check("no duplicated source label",
          mm and mm[0].source.count("conference-data") == 1, f"got {mm[0].source!r}" if mm else "")

    print("\nPage chrome")
    check("no border-radius left in the CSS", "border-radius" not in render.CSS,
          "an element is still rounded")

    _, body3, _ = render_one(Event(name="Kafka Summit", url="https://a.example/",
                                   start=dt.date.today(), country="USA", online=True,
                                   tags=["Streaming & Kafka", "Lakehouse & Table Formats"]))
    check("no exclusion text box — inclusion only", 'id="x"' not in body3)
    check("inclusion search box present", 'id="q"' in body3)
    check("hidden-count element exists (JS derefs it)", 'id="hiddennote"' in body3)
    check("cards carry region keys", 'data-regions="' in body3)
    check("region dropdown rendered", 'id="region-dd"' in body3 and "<details" in body3)
    check("summary has a counts slot", 'id="region-count"' in body3)
    check("topic chips still render", 'data-topic="Streaming &amp; Kafka"' in body3)
    # Filtering is wired through these exact selectors; if an attribute or the
    # selector drifts, clicking a control silently does nothing.
    check("JS selects topic chips by data-topic", ".chip[data-topic]" in render.JS)
    check("JS reads the region checkboxes", "input[type=checkbox][data-region]" in render.JS)
    check("JS restores tick state from storage", "b.checked=!hideRegions.has(" in render.JS)
    check("JS persists the hidden set", "localStorage.setItem(STORE" in render.JS)
    check("JS reads the hidden set", "localStorage.getItem(STORE" in render.JS)
    check("storage access is guarded (private mode throws)",
          render.JS.count("catch(e)") >= 2, "an unguarded localStorage call")
    check("reset re-ticks every region", "b.checked=true;" in render.JS)

    total_boxes = len(re.findall(r'<input type="checkbox" data-region="', body3))
    ticked = len(re.findall(r'<input type="checkbox" data-region="[^"]*" checked>', body3))
    check("every region renders ticked by default",
          total_boxes > 0 and total_boxes == ticked, f"{ticked}/{total_boxes} ticked")

    # An option whose key no card carries would be a dead checkbox, and a card
    # with no region key could never be shown by an include filter.
    opt_keys = re.findall(r'<input type="checkbox" data-region="([^"]*)"', body3)
    card_attrs = re.findall(r'data-cfp="[^"]*" data-regions="([^"]*)"', body3)
    flat: set = set()
    for v in card_attrs:
        flat.update(k for k in v.split("|") if k)
    check("region options rendered", bool(opt_keys), "none rendered")
    check("every card carries at least one region key", all(card_attrs),
          "a card has no region — the include filter would strand it")
    check("every option matches a region some card carries",
          all(c in flat for c in opt_keys),
          f"orphans: {[c for c in opt_keys if c not in flat]}")
    check("Online sorted to the top", bool(opt_keys) and opt_keys[0] == "Online",
          f"first={opt_keys[:1]}")

    # Regression: the controls bar was a scroll container, which clipped the
    # absolutely-positioned dropdown and put a scrollbar on the sticky bar.
    controls_css = re.search(r"\.controls\{([^}]*)\}", render.CSS).group(1)
    check("controls bar is NOT a scroll container", 
          "overflow" not in controls_css and "max-height" not in controls_css,
          f"got: {controls_css!r}")
    menu_css = re.search(r"\.ddmenu\{([^}]*)\}", render.CSS).group(1)
    check("dropdown menu is absolutely positioned", "position:absolute" in menu_css,
          f"got: {menu_css!r}")
    check("dropdown menu stacks above the cards", "z-index" in menu_css)
    check("no other rule sets overflow on an ancestor of the menu",
          not re.search(r"\.(wrap|card)\{[^}]*overflow\s*:", render.CSS),
          "an ancestor clips the menu")
    check("narrow screens unpin the controls bar",
          ".controls{position:static}" in render.CSS,
          "sticky bar will eat the viewport on phones")

    print("\nCountry normalisation")
    from model import normalize_country
    check("'us' and 'USA' collapse to one label",
          normalize_country("us") == "USA" and normalize_country("United States") == "USA")
    check("'uk' and 'United Kingdom' collapse",
          normalize_country("uk") == "UK" and normalize_country("United Kingdom") == "UK")
    check("mixed-case code normalises", normalize_country("Us") == "USA")
    check("unmapped name passes through", normalize_country("Lithuania") == "Lithuania")
    check("unmapped 2-letter code is uppercased", normalize_country("nz") == "NZ")
    check("empty stays empty", normalize_country("") == "")
    one_chip = merge_events([Event(name="A conf", country="us", start=dt.date(2027, 2, 1)),
                             Event(name="B conf", country="USA", start=dt.date(2027, 2, 2))])
    check("merge leaves one country value for the chips",
          len({x.country for x in one_chip}) == 1, f"got {[x.country for x in one_chip]}")

    print("\nRegion mapping (include filter)")
    from render import _region_of, _REGION_BY_COUNTRY, TBA_REGION
    check("US event maps to North America",
          _region_of(Event(name="x", country="USA")) == ["North America"])
    check("online event maps to Online",
          _region_of(Event(name="x", online=True)) == ["Online"])
    check("online + country carries both regions",
          set(_region_of(Event(name="x", country="Germany", online=True))) == {"Online", "Europe"})
    check("location-less event falls back to TBA (never unreachable)",
          _region_of(Event(name="x")) == [TBA_REGION])
    check("unknown country maps to Other",
          _region_of(Event(name="x", country="Wakanda")) == ["Other"])
    check("South Africa maps to Africa, not Asia",
          _region_of(Event(name="x", country="South Africa")) == ["Africa"])
    check("TBA is never a real region name",
          TBA_REGION not in set(_REGION_BY_COUNTRY.values()))

    print("\nVenue normalisation")
    from model import normalize_venue
    v = normalize_venue(Event(name="x", city="Online", country="Online"))
    check("'Online' in city/country becomes an online flag",
          v.online and not v.city and not v.country,
          f"online={v.online} city={v.city!r} country={v.country!r}")
    check("a virtual venue renders as just 'Online'", v.location == "Online",
          f"got {v.location!r}")
    check("such an event is not filed under Other",
          _region_of(v) == ["Online"], f"got {_region_of(v)}")
    real = normalize_venue(Event(name="y", city="Berlin", country="Germany"))
    check("a real venue is left alone",
          real.city == "Berlin" and real.country == "Germany" and not real.online)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S):")
        for f in FAILURES:
            print("  -", f)
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
