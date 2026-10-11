"""Source adapters. Each returns a list[Event] and must never raise."""
from __future__ import annotations

import datetime as dt
import gzip
import json
import pathlib
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from model import Event, parse_date

HERE = pathlib.Path(__file__).resolve().parent

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

WARNINGS: list[str] = []


def warn(msg: str) -> None:
    WARNINGS.append(msg)
    print(f"  [warn] {msg}")


def http_get(url: str, timeout: int = 30, retries: int = 2, as_json: bool = False,
             accept: str = "application/json, text/html;q=0.9, */*;q=0.8"):
    """GET with retries. Returns (status, body) or (None, error-string)."""
    last = "unknown"
    for attempt in range(retries + 1):
        req = urllib.request.Request(url, headers={
            "User-Agent": UA, "Accept": accept, "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip",
        })
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                text = raw.decode("utf-8", "replace")
                return r.status, (json.loads(text) if as_json else text)
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
        except Exception as e:  # noqa: BLE001 - any network failure is a soft failure
            last = f"{type(e).__name__}: {e}"
        if attempt < retries:
            time.sleep(1.5 * (attempt + 1))
    return None, last


def _pmap(fn, items, workers: int = 8):
    """Map fn over items with a bounded thread pool, preserving order.

    Network-bound work dominates this tool, so the whole run is gated by the
    slowest source. Threads keep a nightly rebuild to seconds, not minutes.
    """
    if not items:
        return []
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(items)))) as pool:
        return list(pool.map(fn, items))


# ---------------------------------------------------------------------------
# Source 1: developers.events  (broad, includes CFP deadlines)
# ---------------------------------------------------------------------------

def from_developers_events(today: dt.date) -> list[Event]:
    status, payload = http_get("https://developers.events/all-events.json",
                               timeout=60, as_json=True)
    if status is None:
        warn(f"developers.events unreachable ({payload})")
        return []
    out: list[Event] = []
    for raw in payload:
        dates = raw.get("date") or []
        if not dates:
            continue
        start = parse_date(dates[0])
        if not start or start < today:
            continue
        end = parse_date(dates[-1]) if len(dates) > 1 else None
        cfp = raw.get("cfp") or {}
        out.append(Event(
            name=(raw.get("name") or "").strip(),
            url=raw.get("hyperlink") or "",
            start=start, end=end,
            city=(raw.get("city") or "").strip(),
            country=(raw.get("country") or "").strip(),
            online=bool(raw.get("online")),
            kind="conference",
            source="developers.events",
            source_url="https://developers.events/",
            cfp_url=cfp.get("link") or "",
            cfp_close=parse_date(cfp.get("untilDate") or cfp.get("until")),
            description=strip_html(raw.get("misc") or ""),
        ))
    print(f"  developers.events -> {len(out)} future events")
    return out


# ---------------------------------------------------------------------------
# Source 2: tech-conferences/conference-data (per-topic JSON on GitHub)
# ---------------------------------------------------------------------------

TC_TOPICS_FALLBACK = ["data", "java", "devops", "sre", "api", "general", "javascript",
                      "python", "testing", "performance", "opensource", "product"]

_topic_cache: dict = {}


def _topics_for(year: int) -> list[str]:
    """Discover every topic file for a year (falls back to a static list)."""
    if year in _topic_cache:
        return _topic_cache[year]
    status, payload = http_get(
        "https://api.github.com/repos/tech-conferences/conference-data/contents/"
        f"conferences/{year}", timeout=30, as_json=True)
    topics: list[str] = []
    if isinstance(payload, list):
        topics = [i["name"][:-5] for i in payload
                  if isinstance(i, dict) and str(i.get("name", "")).endswith(".json")]
    if not topics:
        topics = list(TC_TOPICS_FALLBACK)
    _topic_cache[year] = topics
    return topics


def from_tech_conferences(today: dt.date, years=(2026, 2027)) -> list[Event]:
    out: list[Event] = []
    fetched = 0
    pages = {}
    jobs: list[tuple[str, str]] = []
    for year in years:
        base = ("https://raw.githubusercontent.com/tech-conferences/"
                f"conference-data/main/conferences/{year}")
        for topic in _topics_for(year):
            jobs.append((topic, f"{base}/{topic}.json"))
    for job, page in zip(jobs, _pmap(
            lambda j: http_get(j[1], timeout=30, as_json=True), jobs, workers=8)):
        pages[job] = page

    for year in years:
        base = ("https://raw.githubusercontent.com/tech-conferences/"
                f"conference-data/main/conferences/{year}")
        topics = _topics_for(year)
        for topic in topics:
            status, payload = pages.get((topic, f"{base}/{topic}.json"), (None, None))
            if status is None or not isinstance(payload, list):
                continue
            fetched += 1
            for raw in payload:
                start = parse_date(raw.get("startDate"))
                if not start or start < today:
                    continue
                out.append(Event(
                    name=re.sub(r"\s+", " ", (raw.get("name") or "").strip()),
                    url=raw.get("url") or "",
                    start=start,
                    end=parse_date(raw.get("endDate")),
                    city="", country="",
                    online=bool(raw.get("online")),
                    kind="conference",
                    source="conference-data",
                    source_url="https://github.com/tech-conferences/conference-data",
                    cfp_url=raw.get("cfpUrl") or "",
                    cfp_close=parse_date(raw.get("cfpEndDate")),
                    cfp_open=parse_date(raw.get("cfpStartDate")),
                    tags=[topic],
                ))
    if not fetched:
        warn("conference-data: no topic files fetched")
    print(f"  conference-data  -> {len(out)} future events ({fetched} topic files)")
    return out


# ---------------------------------------------------------------------------
# Source 3: Meetup search (schema.org JSON-LD embedded in the find page)
# ---------------------------------------------------------------------------

MEETUP_KEYWORDS = [
    "apache kafka", "kafka", "apache flink", "flink", "data streaming",
    "streaming data", "real time data", "real-time analytics", "data engineering",
    "streaming analytics", "apache iceberg", "iceberg", "apache spark",
    "data platform", "event driven architecture", "event streaming",
    "lakehouse", "apache pinot", "clickhouse", "debezium", "change data capture",
    "apache pulsar", "data infrastructure", "snowflake", "databricks",
    "apache airflow", "dbt", "big data",
]
MEETUP_LOCATIONS = ["us--CA--San Jose", "us--CA--San Francisco", ""]


def from_meetup(today: dt.date) -> list[Event]:
    seen: set[str] = set()
    out: list[Event] = []
    errors = 0
    _urls: list[str] = []
    for _kw in MEETUP_KEYWORDS:
        for _loc in MEETUP_LOCATIONS:
            _u = ("https://www.meetup.com/find/?keywords=" +
                  urllib.parse.quote(_kw) + "&source=EVENTS")
            if _loc:
                _u += "&location=" + urllib.parse.quote(_loc)
            _urls.append(_u)
    _pages = dict(zip(_urls, _pmap(
        lambda u: http_get(u, timeout=30, accept="text/html"), _urls, workers=8)))

    for keyword in MEETUP_KEYWORDS:
        for loc in MEETUP_LOCATIONS:
            url = ("https://www.meetup.com/find/?keywords=" +
                   urllib.parse.quote(keyword) + "&source=EVENTS")
            if loc:
                url += "&location=" + urllib.parse.quote(loc)
            status, html = _pages.get(url, (None, "not fetched"))
            if status is None:
                errors += 1
                continue
            for ev in _parse_meetup_ld(html):
                name = (ev.get("name") or "").strip()
                if not name or name in seen:
                    continue
                start = parse_date((ev.get("startDate") or "")[:10])
                if not start or start < today:
                    continue
                seen.add(name)
                loc = ev.get("location") or {}
                city = country = ""
                online = False
                if isinstance(loc, dict):
                    if loc.get("@type") == "VirtualLocation":
                        online = True
                    addr = loc.get("address") or {}
                    if isinstance(addr, dict):
                        city = (addr.get("addressLocality") or "").strip()
                        country = (addr.get("addressCountry") or "").strip()
                out.append(Event(
                    name=name, url=ev.get("url") or "",
                    start=start, end=parse_date((ev.get("endDate") or "")[:10]),
                    city=city, country=country, online=online,
                    kind="meetup", source="meetup",
                    source_url="https://www.meetup.com/find/",
                ))
    if errors and not out:
        warn(f"meetup: all {errors} queries failed")
    print(f"  meetup           -> {len(out)} future events")
    return out


def _parse_meetup_ld(html: str) -> list[dict]:
    blocks = re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>',
                        html, re.S | re.I)
    events: list[dict] = []
    for blk in blocks:
        try:
            data = json.loads(blk.strip())
        except Exception:  # noqa: BLE001 - malformed LD is not fatal
            continue
        for item in (data if isinstance(data, list) else [data]):
            if isinstance(item, dict) and item.get("@type") == "Event":
                events.append(item)
            elif isinstance(item, dict) and isinstance(item.get("itemListElement"), list):
                for li in item["itemListElement"]:
                    node = li.get("item") if isinstance(li, dict) else None
                    if isinstance(node, dict) and node.get("@type") == "Event":
                        events.append(node)
    return events


# ---------------------------------------------------------------------------
# Source 4: curated flagship "anchor" events the user named
# ---------------------------------------------------------------------------

DATE_RANGE_PATTERNS = [
    # Nov 30-Dec 4, 2026  |  November 30 – December 4, 2026
    (r"([A-Z][a-z]{2,8})\s+(\d{1,2})\s*[-–—]\s*([A-Z][a-z]{2,8})\s+(\d{1,2}),?\s*(\d{4})", "MD_MD_Y"),
    # November 4-5, 2026  |  June 21–24, 2027
    (r"([A-Z][a-z]{2,8})\s+(\d{1,2})\s*[-–—]\s*(\d{1,2}),?\s*(\d{4})", "MD_D_Y"),
    # 13-16 October 2026
    (r"(\d{1,2})\s*[-–—]\s*(\d{1,2})\s+([A-Z][a-z]{2,8})\s+(\d{4})", "D_D_M_Y"),
    # October 2026 (month only)
    (r"\b([A-Z][a-z]{2,8})\s+(\d{4})\b", "M_Y"),
    # Year-less ranges ("Nov 30-Dec 4, Las Vegas") — year inferred from context.
    # Kept last so any year-bearing form above wins first.
    (r"([A-Z][a-z]{2,8})\s+(\d{1,2})\s*[-–—]\s*([A-Z][a-z]{2,8})\s+(\d{1,2})(?!,?\s*\d{4})", "MD_MD_NOY"),
    (r"([A-Z][a-z]{2,8})\s+(\d{1,2})\s*[-–—]\s*(\d{1,2})(?!,?\s*\d{4})", "MD_D_NOY"),
]


def _month(name: str) -> int | None:
    from model import _MONTHS
    return _MONTHS.get(name.lower()[:9]) or _MONTHS.get(name.lower()[:3])


def _year_near(text: str, start: int, end: int, window: int = 120) -> int | None:
    """A single unambiguous 4-digit year adjacent to a date-range match."""
    ctx = text[max(0, start - window): end + window]
    years = {int(y) for y in re.findall(r"\b(20\d\d)\b", ctx)}
    return years.pop() if len(years) == 1 else None


def _infer_year(month: int, today: dt.date) -> int:
    """Year-less range: this year if that month hasn't passed, else next."""
    return today.year if month >= today.month else today.year + 1


def extract_date_range(text: str, today: dt.date | None = None,
                       ) -> tuple[dt.date | None, dt.date | None, str]:
    """Conservatively pull one date range out of page text.

    Returns (start, end, evidence). Only explicit, month-named patterns are
    accepted — a bare year is never treated as a date.
    """
    from model import _MONTHS  # noqa: F401
    today = today or dt.date.today()
    for pattern, kind in DATE_RANGE_PATTERNS:
        found: list[tuple[dt.date, dt.date | None, str]] = []
        for m in re.finditer(pattern, text):
            g = m.groups()
            try:
                if kind == "MD_MD_Y":
                    m1, m2 = _month(g[0]), _month(g[2])
                    if not m1 or not m2:
                        continue
                    y = int(g[4])
                    start = dt.date(y, m1, int(g[1]))
                    end_year = y + 1 if m2 < m1 else y
                    end = dt.date(end_year, m2, int(g[3]))
                elif kind == "MD_D_Y":
                    m1 = _month(g[0])
                    if not m1:
                        continue
                    start = dt.date(int(g[3]), m1, int(g[1]))
                    end = dt.date(int(g[3]), m1, int(g[2]))
                elif kind == "D_D_M_Y":
                    m1 = _month(g[2])
                    if not m1:
                        continue
                    start = dt.date(int(g[3]), m1, int(g[0]))
                    end = dt.date(int(g[3]), m1, int(g[1]))
                elif kind == "MD_MD_NOY":
                    m1, m2 = _month(g[0]), _month(g[2])
                    if not m1 or not m2:
                        continue
                    y = _year_near(text, m.start(0), m.end(0)) or _infer_year(m1, today)
                    start = dt.date(y, m1, int(g[1]))
                    end = dt.date(y + (1 if m2 < m1 else 0), m2, int(g[3]))
                elif kind == "MD_D_NOY":
                    m1 = _month(g[0])
                    if not m1:
                        continue
                    y = _year_near(text, m.start(0), m.end(0)) or _infer_year(m1, today)
                    start = dt.date(y, m1, int(g[1]))
                    end = dt.date(y, m1, int(g[2]))
                else:  # M_Y - month only
                    m1 = _month(g[0])
                    if not m1:
                        continue
                    start = dt.date(int(g[1]), m1, 1)
                    end = None
            except (ValueError, TypeError):
                continue
            if end and end < start:
                start, end = end, start
            found.append((start, end, m.group(0)))
        if found:
            # Prefer the next upcoming range; fall back to the first match.
            upcoming = [c for c in found if c[0] >= today]
            return upcoming[0] if upcoming else found[0]
    return None, None, ""


def _visible_text(html: str) -> str:
    title = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    heads = " ".join(re.findall(r"<h[1-3][^>]*>(.*?)</h[1-3]>", html, re.S | re.I))
    body = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    body = re.sub(r"<[^>]+>", " ", body)
    body = (body.replace("&nbsp;", " ").replace("&amp;", "&")
                .replace("&#8211;", "–").replace("&#8212;", "—").replace("&ndash;", "–"))
    def clean(s):
        return re.sub(r"\s+", " ", s)
    # Title/headings first: highest signal, least chance of a footer date.
    return clean(f"{title.group(1) if title else ''} {heads} ") + " ||| " + clean(body)


def from_anchors(today: dt.date, refresh: bool = True) -> list[Event]:
    """Flagship events the user named. Curated dates are the floor; a live page
    scrape may confirm/update them and records the evidence string."""
    path = HERE / "anchors.json"
    if not path.exists():
        warn("anchors.json missing")
        return []
    spec = json.loads(path.read_text())
    out: list[Event] = []
    for a in spec.get("events", []):
        start, end = _parse_iso_range(a.get("dates", ""))
        note = a.get("cfp_note", "")
        evidence = a.get("dates_evidence", "")
        verified = bool(a.get("verified", False))
        if refresh and a.get("url") and a.get("refresh", True):
            status, html = http_get(a["url"], timeout=30, accept="text/html", retries=1)
            if status is None:
                note = (note + f" · [fetch failed: {html}]").strip(" ·")
            else:
                s2, e2, ev = extract_date_range(_visible_text(html), today)
                if s2 and s2 >= today and ev:
                    if s2 != start or e2 != end:
                        print(f"  anchor date update: {a['name']} "
                              f"{start}..{end} -> {s2}..{e2}  (evidence: {ev!r})")
                    start, end, evidence, verified = s2, e2, ev, True
                elif start:
                    evidence = evidence or ""
        out.append(Event(
            name=a["name"], url=a.get("url", ""),
            start=start, end=end,
            city=a.get("city", ""), country=a.get("country", ""),
            online=bool(a.get("online", False)),
            kind="conference", source="curated",
            source_url=a.get("url", ""),
            cfp_url=a.get("cfp_url", ""),
            cfp_close=parse_date(a.get("cfp_close")),
            cfp_note=note, description=a.get("description", ""),
            tags=["flagship"], verified=verified, anchor=True,
        ))
        # stale curated dates shouldn't masquerade as current
        if out[-1].start and out[-1].end and out[-1].end < today:
            out[-1].start = out[-1].end = None
            out[-1].cfp_note = (out[-1].cfp_note + " · next edition dates TBA").strip(" ·")
    print(f"  anchors          -> {len(out)} events")
    return out


def _parse_iso_range(s: str):
    if not s or "/" not in s:
        d = parse_date(s) if s else None
        return d, d
    a, b = s.split("/", 1)
    return parse_date(a), parse_date(b)


def strip_html(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", s).strip()


def collect_all(today: dt.date, refresh_anchors: bool = True) -> list[Event]:
    events: list[Event] = []
    for name, fn in (
        ("developers.events", lambda: from_developers_events(today)),
        ("conference-data", lambda: from_tech_conferences(today)),
        ("meetup", lambda: from_meetup(today)),
        ("anchors", lambda: from_anchors(today, refresh=refresh_anchors)),
    ):
        try:
            events.extend(fn())
        except Exception as e:  # noqa: BLE001 - isolate source failures
            warn(f"{name} raised {type(e).__name__}: {e}")
    return events
