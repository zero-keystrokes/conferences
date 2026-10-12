# Streaming &amp; Data Events

A nightly-updated page of conferences, meetups and **call-for-papers deadlines**
for Kafka, Flink, stream processing, lakehouse and data engineering.

**Live:** https://zero-keystrokes.github.io/conferences/

Updated every night at 03:15 by a Hermes cron job. The page is a single static
HTML file — no build step at serve time, no JavaScript framework, no external
requests. It works offline once loaded.

---

## What the page shows

| Section | What it is |
|---|---|
| **CFPs closing soon** | Call-for-papers deadlines in the next 60 days. This is the actionable list — an event appears here while its conference may still be months away, because the *deadline* is the thing with a clock on it. |
| **Events in the next 3 months** | The three-month outlook, grouped by month. |
| **Announced beyond 3 months** | Dated events further out (up to ~13 months), for planning. |
| **Watchlist** | Flagship events in this space whose next edition has no published dates yet. They leave this list automatically once a date appears. |

Each card carries the event's dates, location, whether it's online, the source it
came from, topic tags, and — where one exists — a CFP box with the closing date,
days remaining and a direct submission link.

Client-side filters run over the rendered HTML; nothing is fetched at view time.

**Inclusion** — topic chips, a "CFP open only" toggle, and a free-text search
over name, city, source and tags.

**Exclusion** — the second box takes comma-separated terms (`online, berlin,
singapore`) and hides anything matching, plus a row of one-click **Hide** chips
for country and online-ness. A running count shows how many cards your
exclusions removed, and `reset` clears both directions. Topic, search and
exclusion combine: you can narrow to `kafka` and still exclude `online`.

---

## Data sources

Four sources, each independently failure-isolated. A source that is down adds a
warning to the page footer and the page still builds.

1. **developers.events** — [`all-events.json`](https://developers.events/all-events.json),
   an open conference feed with CFP deadlines. Broad but shallow on the
   commercial data-vendor events.
2. **tech-conferences/conference-data** — per-topic, per-year JSON on GitHub,
   including `data.json`. Every topic file is discovered dynamically per year.
3. **meetup.com** — the event search page embeds `schema.org` JSON-LD `Event`
   objects, which are parsed directly. Queried across ~28 streaming/data keywords
   and three locations.
4. **Curated flagship list** — `generator/anchors.json`. The named events of
   interest (Current/Confluent, AWS re:Invent, Iceberg Summit, Databricks
   Data + AI Summit, and neighbours like Apache Community Over Code, QCon,
   Data Council, Flink Forward). Dates here are the floor; the nightly run also
   scrapes each event's own page.

### How dates are kept honest

Every date on the page is either read from the event's own listing or from an
aggregator feed. The scraper only accepts an explicit **month-named** pattern
(`Nov 30-Dec 4`, `June 21–24, 2027`, `13-16 October 2026`) and only if the
resulting date falls on or after today. That second condition matters: several
event sites carry stale years in archive copy, and a naive scrape will happily
read `December 2012` off a page. A date is never inferred from a bare year, and
an unknown date stays **TBA** rather than being guessed.

When a date is read from an event's own site, the card shows a `first-party`
badge.

---

## Layout

```
conferences/
├── docs/                 # the published site (index.html, events.json, .nojekyll)
├── generator/
│   ├── build.py          # entry point: collect -> score -> dedupe -> render
│   ├── sources.py        # the four source adapters + HTTP layer
│   ├── classify.py       # topic keywords and relevance scoring
│   ├── model.py          # Event dataclass, date parsing, dedupe/merge
│   ├── render.py         # self-contained HTML generation
│   ├── anchors.json      # curated flagship events (edit this to add yours)
│   ├── collect_cache.py  # cache a raw pull for offline tuning
│   └── tune.py           # inspect classifier output against a cached pull
├── tests_filters.mjs     # runs the shipped filter JS against the shipped markup
├── nightly.sh            # what cron runs
└── raw-cache.json        # gitignored scratch
```

## Running it

```bash
python3 generator/build.py                 # build into docs/
python3 generator/build.py --publish       # build, commit and push
python3 generator/build.py --no-anchor-refresh
```

Python 3 standard library only — no dependencies to install.

To tune the relevance filter without hammering the network:

```bash
python3 generator/collect_cache.py         # cache one raw pull (~20s)
python3 generator/tune.py --min 4          # see what scores and what is dropped
```

## Adding an event to the watchlist

Edit `generator/anchors.json`. `dates` is `"YYYY-MM-DD/YYYY-MM-DD"` (leave `""`
if unknown). Set `"refresh": false` for a URL that does not resolve, so nightly
runs stay quiet.

## Relevance

`classify.py` scores each event across five topic buckets with weighted
keywords, matched on name, tags, description and URL. A negative list drops
noise that rides on generic data vocabulary — language-exchange groups, course
and job-hunting ads. The matched terms and score are printed on each card, so
you can see exactly why an event is on the page.
