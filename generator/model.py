"""Core data model for the Streaming & Data Events tracker."""
from __future__ import annotations

import datetime as dt
import hashlib
import re
from dataclasses import dataclass, field, asdict
from typing import Optional

# ----------------------------------------------------------------------------
# Date handling
# ----------------------------------------------------------------------------

ISO = "%Y-%m-%d"

_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}


def parse_date(value, today: Optional[dt.date] = None) -> Optional[dt.date]:
    """Best-effort date parser. Returns None rather than guessing.

    Accepts ISO (YYYY-MM-DD), 'DD-Month-YYYY' (developers.events style),
    leading-whitespace variants, and datetime objects. Anything else -> None.
    """
    if value is None or value == "":
        return None
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, (int, float)):
        # epoch millis used by developers.events
        try:
            return dt.datetime.fromtimestamp(value / 1000, dt.UTC).date()
        except (OverflowError, OSError, ValueError):
            return None

    s = str(value).strip()
    if not s:
        return None

    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        try:
            return dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None

    m = re.match(r"^(\d{1,2})-([A-Za-z]{3,9})-(\d{4})$", s)
    if m:
        mon = _MONTHS.get(m.group(2).lower())
        if mon:
            try:
                return dt.date(int(m.group(3)), mon, int(m.group(1)))
            except ValueError:
                return None

    m = re.match(r"^([A-Za-z]{3,9})\s+(\d{1,2}),?\s+(\d{4})$", s)
    if m:
        mon = _MONTHS.get(m.group(1).lower())
        if mon:
            try:
                return dt.date(int(m.group(3)), mon, int(m.group(2)))
            except ValueError:
                return None

    return None


def to_iso(d: Optional[dt.date]) -> Optional[str]:
    return d.isoformat() if d else None


# ----------------------------------------------------------------------------
# Event
# ----------------------------------------------------------------------------

@dataclass
class Event:
    name: str
    url: str = ""
    start: Optional[dt.date] = None
    end: Optional[dt.date] = None
    city: str = ""
    country: str = ""
    online: bool = False
    kind: str = "conference"          # conference | meetup | webinar
    source: str = ""
    source_url: str = ""
    cfp_url: str = ""
    cfp_close: Optional[dt.date] = None
    cfp_open: Optional[dt.date] = None
    cfp_note: str = ""
    description: str = ""
    tags: list = field(default_factory=list)
    score: int = 0
    matched: list = field(default_factory=list)
    verified: bool = False            # True when dates came from a first-party source
    anchor: bool = False              # user-named flagship event

    # -- derived ------------------------------------------------------------
    @property
    def dedupe_key(self) -> str:
        """Stable identity for cross-source dedupe: normalised name + month."""
        n = re.sub(r"[^a-z0-9 ]+", " ", self.name.lower())
        n = re.sub(r"\b(19|20)\d\d\b", " ", n)
        n = re.sub(r"\b(the|a|an|and|of|for|conference|conf|summit|meetup|"
                   r"20\d\d|annual|edition|virtual|online)\b", " ", n)
        n = re.sub(r"\s+", " ", n).strip()
        month = self.start.strftime("%Y-%m") if self.start else "nodate"
        return hashlib.sha1(f"{n}|{month}".encode()).hexdigest()[:16]

    @property
    def location(self) -> str:
        if self.online and not self.city:
            return "Online"
        bits = [b for b in (self.city, self.country) if b]
        loc = ", ".join(bits) if bits else "Location TBA"
        return f"{loc} + Online" if self.online and self.city else loc

    @property
    def date_label(self) -> str:
        if not self.start:
            return "Dates TBA"
        if not self.end or self.end == self.start:
            return self.start.strftime("%b %-d, %Y")
        if self.start.year == self.end.year and self.start.month == self.end.month:
            return f"{self.start.strftime('%b %-d')}–{self.end.strftime('%-d, %Y')}"
        return f"{self.start.strftime('%b %-d, %Y')} – {self.end.strftime('%b %-d, %Y')}"

    @property
    def cfp_days_left(self) -> Optional[int]:
        if not self.cfp_close:
            return None
        return (self.cfp_close - dt.date.today()).days

    @property
    def cfp_state(self) -> str:
        """open | closing-soon | closed | unknown"""
        if not self.cfp_close:
            return "open" if self.cfp_url else "unknown"
        d = self.cfp_days_left
        if d is None:
            return "unknown"
        if d < 0:
            return "closed"
        if d <= 14:
            return "closing-soon"
        return "open"

    def to_dict(self) -> dict:
        d = asdict(self)
        for k in ("start", "end", "cfp_close", "cfp_open"):
            d[k] = to_iso(d[k])
        d.update({
            "location": self.location,
            "date_label": self.date_label,
            "cfp_days_left": self.cfp_days_left,
            "cfp_state": self.cfp_state,
            "id": self.dedupe_key,
        })
        return d


# ----------------------------------------------------------------------------
# Dedupe / merge
# ----------------------------------------------------------------------------

def _richness(e: Event) -> int:
    """How much usable information an Event carries — used to pick a winner."""
    r = 0
    for v in (e.url, e.city, e.country, e.description, e.cfp_url):
        if v:
            r += 1
    if e.start:
        r += 2
    if e.end:
        r += 1
    if e.cfp_close:
        r += 2
    if e.anchor:
        r += 5
    if e.verified:
        r += 3
    return r


# Words that carry no identity — two events sharing only these are not the same
# event. Domain terms like "data" and "kafka" are deliberately kept.
_GENERIC_TOKENS = {
    "the", "a", "an", "and", "of", "for", "with", "from", "into", "on", "in",
    "at", "to", "by", "is", "are", "your", "our",
    "conference", "conf", "summit", "meetup", "workshop", "event", "events",
    "series", "expo", "forum", "day", "days", "annual", "edition", "virtual",
    "online", "live", "session", "sessions", "talk", "talks",
}


def _sig_tokens(name: str) -> set:
    """Significant words in an event name, for cross-source identity matching."""
    n = re.sub(r"[^a-z0-9 ]+", " ", (name or "").lower())
    return {t for t in n.split()
            if len(t) >= 3
            and t not in _GENERIC_TOKENS
            and not re.fullmatch(r"(19|20)\d\d", t)}


def _absorb(best: "Event", other: "Event") -> "Event":
    """Union a runner-up record into the winner: fill blanks, merge tags/sources."""
    best.url = best.url or other.url
    best.city = best.city or other.city
    best.country = best.country or other.country
    best.start = best.start or other.start
    best.end = best.end or other.end
    best.cfp_url = best.cfp_url or other.cfp_url
    best.cfp_close = best.cfp_close or other.cfp_close
    best.cfp_open = best.cfp_open or other.cfp_open
    best.cfp_note = best.cfp_note or other.cfp_note
    best.description = best.description or other.description
    best.verified = best.verified or other.verified
    best.anchor = best.anchor or other.anchor
    # Split first: `best.source` may already be "A + B", and set-unioning the
    # joined string would emit "A + B + A" style duplicates.
    names = {s.strip() for s in best.source.split("+") if s.strip()}
    names.update(s.strip() for s in other.source.split("+") if s.strip())
    best.source = " + ".join(sorted(names))
    for t in other.tags:
        if t not in best.tags:
            best.tags.append(t)
    return best


def merge_events(events: list) -> list:
    """Collapse duplicates, keeping the richest record and unioning tags."""
    buckets: dict[str, list] = {}
    for e in events:
        if not e.name.strip():
            continue
        buckets.setdefault(e.dedupe_key, []).append(e)

    merged = []
    for group in buckets.values():
        group.sort(key=_richness, reverse=True)
        best = group[0]
        for other in group[1:]:
            _absorb(best, other)
        merged.append(best)

    # Second pass. The same event reaches us under different names — "OSA CON
    # 2026: The Anti-Hype Conference for Open Source Analytics" and "Open Source
    # Analytics Conference" share no dedupe key. Sharing a start date plus two
    # or more significant name tokens is a reliable cross-source signal; both
    # conditions are required so distinct events on a busy day stay separate.
    out: list = []
    for e in sorted(merged, key=_richness, reverse=True):
        if not e.start:
            out.append(e)
            continue
        tokens = _sig_tokens(e.name)
        hit = None
        for cand in out:
            if cand.start and cand.start == e.start and len(tokens & _sig_tokens(cand.name)) >= 2:
                hit = cand
                break
        if hit is None:
            out.append(e)
        else:
            _absorb(hit, e)
    return out
