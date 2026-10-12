"""Render the static site. Everything scraped is HTML-escaped — this page is public."""
from __future__ import annotations

import datetime as dt
import html
import json
import re
from collections import Counter

from model import Event

CSS = """
:root{
  --bg:#0f1420; --panel:#161d2d; --panel2:#1c2436; --line:#2a3550;
  --text:#e8edf7; --muted:#93a1bf; --accent:#38d6c4; --accent2:#ffb454;
  --danger:#ff7a7a; --ok:#5ddc8b;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
  font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,sans-serif}
a{color:var(--accent);text-decoration:none}
a:hover{text-decoration:underline}
.wrap{max-width:1080px;margin:0 auto;padding:28px 20px 72px}
header.top{border-bottom:1px solid var(--line);padding-bottom:18px;margin-bottom:8px}
h1{margin:0 0 6px;font-size:27px;letter-spacing:-.4px}
h1 .spark{color:var(--accent2)}
.sub{color:var(--muted);font-size:13.5px}
.sub b{color:var(--text)}
.stats{display:flex;flex-wrap:wrap;gap:10px;margin:18px 0 4px}
.stat{background:var(--panel);border:1px solid var(--line);padding:10px 14px;min-width:112px}
.stat .n{font-size:21px;font-weight:650;color:var(--accent)}
.stat .l{font-size:11.5px;color:var(--muted);text-transform:uppercase;letter-spacing:.5px}
.stat.warn .n{color:var(--accent2)}
h2{font-size:17px;margin:34px 0 4px;display:flex;align-items:center;gap:9px}
h2 .cnt{font-size:12px;color:var(--muted);font-weight:400}
h2::before{content:"";width:4px;height:17px;background:var(--accent)}
.hint{color:var(--muted);font-size:13px;margin:0 0 14px}
.controls{position:sticky;top:0;z-index:5;background:var(--bg);
  border-bottom:1px solid var(--line);padding:12px 0 10px;margin-top:18px;
  display:flex;flex-wrap:wrap;gap:8px;align-items:center;max-height:46vh;overflow:auto}
.ctlrow{flex-basis:100%;display:flex;flex-wrap:wrap;gap:8px;align-items:center}
.ctlbl{color:var(--muted);font-size:11.5px;text-transform:uppercase;letter-spacing:.6px}
input[type=search]{background:var(--panel);border:1px solid var(--line);color:var(--text);
  padding:8px 12px;font-size:13.5px;min-width:180px;flex:1}
input[type=search].excl{border-color:color-mix(in srgb,var(--danger) 45%,var(--line))}
.chip{background:var(--panel);border:1px solid var(--line);color:var(--muted);
  padding:5px 12px;font-size:12.5px;cursor:pointer;user-select:none}
.chip .ct{opacity:.6;font-size:11px}
.chip[aria-pressed=true]{border-color:var(--accent);color:var(--accent);
  background:color-mix(in srgb,var(--accent) 12%,var(--panel))}
.dd{position:relative;display:inline-block}
.dd>summary{list-style:none;cursor:pointer;background:var(--panel);border:1px solid var(--line);
  color:var(--muted);padding:5px 12px;font-size:12.5px;user-select:none}
.dd>summary::-webkit-details-marker{display:none}
.dd>summary::after{content:" ▾";opacity:.65}
.dd[open]>summary{border-color:var(--accent);color:var(--accent)}
.dd.active>summary{border-color:var(--danger);color:var(--danger)}
.ddmenu{position:absolute;z-index:20;top:calc(100% + 6px);left:0;min-width:230px;
  background:var(--panel2);border:1px solid var(--line);padding:7px;
  max-height:58vh;overflow:auto;display:flex;flex-direction:column}
.ddmenu label{display:flex;align-items:center;gap:9px;padding:6px 8px;font-size:13px;
  color:var(--text);cursor:pointer;white-space:nowrap}
.ddmenu label:hover{background:var(--panel)}
.ddmenu .ct{margin-left:auto;color:var(--muted);font-size:11.5px}
.ddmenu input{margin:0;accent-color:var(--accent)}
.hiddennote{color:var(--danger);font-size:12.5px}
.month{font-size:13px;color:var(--muted);text-transform:uppercase;letter-spacing:.8px;
  margin:22px 0 9px;border-bottom:1px dashed var(--line);padding-bottom:5px}
.card{background:var(--panel);border:1px solid var(--line);
  padding:14px 16px;margin-bottom:10px;border-left:3px solid var(--line)}
.card.flagship{border-left-color:var(--accent2);background:var(--panel2)}
.card.cfp-closing{border-left-color:var(--danger)}
.card.cfp-open{border-left-color:var(--ok)}
.card h3{margin:0 0 5px;font-size:15.5px;font-weight:600;line-height:1.35}
.meta{color:var(--muted);font-size:13px;display:flex;flex-wrap:wrap;gap:5px 14px;margin-bottom:7px}
.meta .d{color:var(--accent);font-weight:600}
.badge{display:inline-block;font-size:10.5px;padding:2px 8px;
  border:1px solid var(--line);color:var(--muted);margin-right:5px;text-transform:uppercase;
  letter-spacing:.4px}
.badge.t{color:var(--accent);border-color:color-mix(in srgb,var(--accent) 45%,var(--line))}
.badge.cfp{color:var(--ok);border-color:color-mix(in srgb,var(--ok) 45%,var(--line))}
.badge.soon{color:var(--danger);border-color:color-mix(in srgb,var(--danger) 50%,var(--line))}
.badge.flag{color:var(--accent2);border-color:color-mix(in srgb,var(--accent2) 50%,var(--line))}
.cfpbox{margin-top:9px;background:var(--panel2);border:1px solid var(--line);
  padding:9px 11px;font-size:13px}
.cfpbox.closing{border-color:color-mix(in srgb,var(--danger) 45%,var(--line))}
.cfpbox .row{display:flex;flex-wrap:wrap;gap:4px 12px;align-items:baseline}
.cfpbox .lbl{color:var(--muted);font-size:11.5px;text-transform:uppercase;letter-spacing:.4px}
.cfpbox .val{font-weight:600}
.cfpbox .note{color:var(--muted);font-size:12.5px;margin-top:5px}
.why{color:var(--muted);font-size:11.5px;margin-top:7px}
.why code{background:var(--panel2);padding:1px 5px;font-size:11px}
.empty{color:var(--muted);padding:18px;border:1px dashed var(--line)}
footer{margin-top:44px;border-top:1px solid var(--line);padding-top:16px;
  color:var(--muted);font-size:12.5px}
footer ul{margin:8px 0 0;padding-left:18px}
.warnbox{background:color-mix(in srgb,var(--accent2) 10%,var(--panel));
  border:1px solid color-mix(in srgb,var(--accent2) 35%,var(--line));
  padding:11px 14px;font-size:12.5px;color:var(--muted);margin-top:16px}
.warnbox b{color:var(--accent2)}
@media(max-width:600px){h1{font-size:22px}.wrap{padding:18px 14px 60px}}
"""

JS = """
const cards=[...document.querySelectorAll('.card')];
const q=document.getElementById('q');
const boxes=[...document.querySelectorAll('input[type=checkbox][data-excl]')];
let topics=new Set(), cfpOnly=false, hideKeys=new Set();
function apply(){
  const term=(q.value||'').trim().toLowerCase();
  let shown=0, hidden=0;
  cards.forEach(c=>{
    const cardTopics=(c.dataset.topics||'').split('|').filter(Boolean);
    const okTopic=topics.size===0||cardTopics.some(t=>topics.has(t));
    const okCfp=!cfpOnly||['open','closing-soon'].includes(c.dataset.cfp);
    const okTerm=!term||(c.dataset.text||'').includes(term);
    const keys=(c.dataset.excl||'').split('|').filter(Boolean);
    const excluded=keys.some(k=>hideKeys.has(k));
    const on=okTopic&&okCfp&&okTerm&&!excluded;
    c.style.display=on?'':'none';
    if(on){shown++;}else if(excluded){hidden++;}
  });
  document.querySelectorAll('.month').forEach(m=>{
    let n=0,s=m.nextElementSibling;
    while(s&&!s.classList.contains('month')&&s.tagName!=='H2'){
      if(s.classList.contains('card')&&s.style.display!=='none')n++;
      s=s.nextElementSibling;
    }
    m.style.display=n?'':'none';
  });
  document.getElementById('noshow').style.display=shown?'none':'block';
  document.getElementById('hiddennote').textContent=
    hidden?hidden+' hidden by your exclusions':'';
  const n=hideKeys.size;
  const cnt=document.getElementById('excl-count');
  if(cnt)cnt.textContent=n?' \\u2014 '+n+' selected':'';
  const dd=document.getElementById('excl-dd');
  if(dd)dd.classList.toggle('active',n>0);
}
function tap(el,fn){
  if(!el)return;
  el.addEventListener('click',fn);
  el.addEventListener('keydown',ev=>{
    if(ev.key==='Enter'||ev.key===' '){ev.preventDefault();fn();}
  });
}
document.querySelectorAll('.chip[data-topic]').forEach(ch=>tap(ch,()=>{
  const t=ch.dataset.topic;
  if(topics.has(t)){topics.delete(t);}else{topics.add(t);}
  ch.setAttribute('aria-pressed',topics.has(t));
  apply();
}));
document.querySelectorAll('input[type=checkbox][data-excl]').forEach(b=>{
  b.addEventListener('change',()=>{
    if(b.checked){hideKeys.add(b.dataset.excl);}else{hideKeys.delete(b.dataset.excl);}
    apply();
  });
});
tap(document.querySelector('.chip.cfp'),()=>{
  cfpOnly=!cfpOnly;
  document.querySelector('.chip.cfp').setAttribute('aria-pressed',cfpOnly);
  apply();
});
q.addEventListener('input',apply);
tap(document.getElementById('reset'),()=>{
  topics.clear();cfpOnly=false;hideKeys.clear();q.value='';
  boxes.forEach(b=>{b.checked=false;});
  document.querySelectorAll('.chip').forEach(c=>c.setAttribute('aria-pressed','false'));
  apply();
});
document.addEventListener('click',ev=>{
  const dd=document.getElementById('excl-dd');
  if(dd&&dd.open&&!dd.contains(ev.target))dd.open=false;
});
apply();
"""


def e(s) -> str:
    return html.escape(str(s or ""), quote=True)


def safe_url(u) -> str:
    """Allow only http(s) into an href.

    Event names and URLs are scraped from third-party pages, and this page is
    public: a `javascript:` or `data:` URL landing in an href is a live XSS
    vector. Anything that is not http(s) is dropped rather than escaped.
    """
    if not u:
        return ""
    s = str(u).strip()
    return s if re.match(r"^https?://", s, re.I) else ""


def _excl_keys(ev: Event) -> list:
    """Values the "Hide" chips can switch on.

    Country and online-ness are the coarse geography knobs worth a one-click
    toggle. Cities deliberately stay out of the chip row (there are far too
    many) and are reachable through the free-text exclude box instead.
    """
    keys = []
    if ev.country:
        keys.append(ev.country)
    if ev.online:
        keys.append("Online")
    return keys


def _badges(ev: Event) -> str:
    out = []
    if ev.anchor:
        out.append('<span class="badge flag">flagship</span>')
    if ev.kind == "meetup":
        out.append('<span class="badge">meetup</span>')
    elif ev.kind == "webinar":
        out.append('<span class="badge">webinar</span>')
    state = ev.cfp_state
    if state == "closing-soon":
        out.append('<span class="badge soon">CFP closing</span>')
    elif state == "open" and ev.cfp_url:
        out.append('<span class="badge cfp">CFP open</span>')
    for t in ev.tags[:3]:
        if t in ("flagship",) or t.isdigit() or len(t) > 26:
            continue
        out.append(f'<span class="badge t">{e(t)}</span>')
    return "".join(out)


def _why(ev: Event) -> str:
    if ev.anchor or not ev.matched:
        return ""
    kw = ", ".join(f"<code>{e(k)}</code>" for k in ev.matched[:6])
    return f'<div class="why">matched on {kw} · relevance {ev.score:.0f}</div>'


def _cfp_box(ev: Event) -> str:
    state = ev.cfp_state
    if not (ev.cfp_url or ev.cfp_close or ev.cfp_note):
        return ""
    cls = "cfpbox closing" if state == "closing-soon" else "cfpbox"
    rows = []
    if ev.cfp_close:
        left = ev.cfp_days_left
        if left is not None and left >= 0:
            days = f"{left} day{'s' if left != 1 else ''} left"
        elif left is not None:
            days = "closed"
        else:
            days = ""
        rows.append(f'<span class="lbl">CFP closes</span>'
                    f'<span class="val">{e(ev.cfp_close.strftime("%b %d, %Y"))}</span>'
                    + (f'<span class="lbl">{e(days)}</span>' if days else ""))
    elif ev.cfp_url:
        rows.append('<span class="lbl">CFP</span><span class="val">open — no deadline published</span>')
    else:
        rows.append('<span class="lbl">CFP</span><span class="val">no open call for papers</span>')
    if ev.cfp_url:
        href = safe_url(ev.cfp_url)
        rows.append(f'<a href="{e(href)}" target="_blank" rel="noopener noreferrer">'
                    f'Submit a talk →</a>' if href else "")
    note = f'<div class="note">{e(ev.cfp_note)}</div>' if ev.cfp_note else ""
    return f'<div class="{cls}"><div class="row">{"".join(rows)}</div>{note}</div>'


def _card(ev: Event) -> str:
    state = ev.cfp_state
    cls = "card"
    if ev.anchor:
        cls += " flagship"
    if ev.cfp_close and state in ("open", "closing-soon"):
        cls += " cfp-closing" if state == "closing-soon" else " cfp-open"
    text = f"{ev.name} {ev.location} {ev.source} {' '.join(ev.tags)}".lower()
    topics = "|".join(t for t in ev.tags if not t.isdigit() and len(t) < 26)
    excl = "|".join(_excl_keys(ev))
    href = safe_url(ev.url)
    link = (f'<a href="{e(href)}" target="_blank" rel="noopener noreferrer">{e(ev.name)}</a>'
            if href else e(ev.name))
    verified = (' <span class="badge" title="dates read from the event\'s own site">'
                'first-party</span>') if ev.verified and ev.anchor else ""
    return (
        f'<div class="{cls}" data-topics="{e(topics)}" data-cfp="{e(state)}" '
        f'data-excl="{e(excl)}" data-text="{e(text)}">'
        f'<h3>{link}{verified}</h3>'
        f'<div class="meta"><span class="d">{e(ev.date_label)}</span>'
        f'<span>{e(ev.location)}</span><span>{e(ev.source)}</span></div>'
        f'<div>{_badges(ev)}</div>'
        f'{_cfp_box(ev)}{_why(ev)}'
        f'</div>'
    )


def _section(title: str, events: list[Event], hint: str = "", group_by_month: bool = False) -> str:
    if not events:
        return ""
    out = [f"<h2>{e(title)}<span class='cnt'>{len(events)}</span></h2>"]
    if hint:
        out.append(f'<p class="hint">{e(hint)}</p>')
    if group_by_month:
        buckets: dict[str, list[Event]] = {}
        for ev in events:
            key = ev.start.strftime("%B %Y") if ev.start else "Dates to be announced"
            buckets.setdefault(key, []).append(ev)
        for month, group in buckets.items():
            out.append(f'<div class="month">{e(month)}</div>')
            out.extend(_card(x) for x in group)
    else:
        out.extend(_card(x) for x in events)
    return "".join(out)


def json_for_html(obj) -> str:
    """Serialize JSON for embedding inside a <script> block.

    Escaping `<`, `>` and `&` — not just the `</script` sequence — keeps the
    payload inert no matter what the scraper captured. Without this, a scraped
    event name containing markup is still parseable out of the document by
    anything that reads the JSON block, even though the rendered card is safe.
    """
    return (json.dumps(obj, default=str)
            .replace("<", "\\u003c")
            .replace(">", "\\u003e")
            .replace("&", "\\u0026"))


def clean_payload(events: list[Event]) -> list[dict]:
    """Export event dicts with only http(s) URLs, so consumers of events.json
    inherit the same allowlist the page applies."""
    out = []
    for x in events:
        d = x.to_dict()
        for key in ("url", "cfp_url", "source_url"):
            if key in d:
                d[key] = safe_url(d.get(key))
        out.append(d)
    return out


def render(events: list[Event], meta: dict) -> str:
    today = meta["today"]
    win_start = meta["window_start"]
    win_end = meta["window_end"]
    horizon = meta.get("horizon_end")

    in_window = [x for x in events if x.start and win_start <= x.start <= win_end]
    undated = [x for x in events if not x.start]
    beyond = sorted([x for x in events if x.start and x.start > win_end], key=lambda x: x.start)
    if horizon:
        beyond = [x for x in beyond if x.start <= horizon]

    # A CFP deadline is actionable regardless of how far out the event itself is —
    # for a conference six months away the deadline is the only thing that matters now.
    closing = sorted([x for x in events if x.cfp_close
                      and 0 <= (x.cfp_days_left or 0) <= 60], key=lambda x: x.cfp_close)
    cfp_open = [x for x in in_window if x.cfp_url and x.cfp_state in ("open", "closing-soon")]
    anchors = [x for x in events if x.anchor]

    topics = sorted({t for x in events for t in x.tags if not t.isdigit() and len(t) < 26})

    chips = "".join(
        f'<span class="chip" role="button" tabindex="0" aria-pressed="false" '
        f'data-topic="{e(t)}">{e(t)}</span>' for t in topics)

    key_counts: Counter = Counter()
    for ev in events:
        for k in _excl_keys(ev):
            key_counts[k] += 1
    # Online first (the exclusion people reach for most), then by how many
    # events each option would hide, so the ones that matter sit at the top.
    ordered_keys = sorted(key_counts.items(),
                          key=lambda kv: (kv[0] != "Online", -kv[1], kv[0]))
    dd_opts = "".join(
        f'<label><input type="checkbox" data-excl="{e(k)}"> {e(k)}'
        f'<span class="ct">{n}</span></label>' for k, n in ordered_keys)
    excl_dd = ('<details class="dd" id="excl-dd">'
               '<summary>Exclude<span id="excl-count"></span></summary>'
               f'<div class="ddmenu">{dd_opts}</div></details>') if dd_opts else ""

    # Each event renders in exactly one section — a flagship with confirmed dates
    # belongs in the calendar, not repeated in a watchlist.
    body = [
        _section("CFPs closing soon", closing,
                 "Call-for-papers deadlines in the next 60 days — the actionable list. "
                 "An event can sit here while its conference is still months away."),
        _section("Events in the next 3 months", in_window,
                 f"{win_start.strftime('%b %d')} – {win_end.strftime('%b %d, %Y')}, grouped by month.",
                 group_by_month=True),
        _section("Announced beyond 3 months", beyond,
                 "Worth planning around, but outside the three-month outlook."),
        _section("Watchlist — dates not published yet", undated,
                 "Flagship events in this space whose next edition has no published dates. "
                 "They move out of this list automatically once a date appears."),
    ]
    sections = "".join(body)
    if not sections:
        sections = '<div class="empty">No events matched any source on this run.</div>'

    warnings = meta.get("warnings") or []
    warnbox = ""
    if warnings:
        items = "".join(f"<li>{e(w)}</li>" for w in warnings)
        warnbox = (f'<div class="warnbox"><b>Source warnings this run</b> '
                   f'(the page still built without them):<ul>{items}</ul></div>')

    payload = json_for_html(clean_payload(events))

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Streaming &amp; Data Events — Kafka, Flink, lakehouse and data conferences</title>
<meta name="description" content="Conferences, meetups and call-for-papers deadlines for Kafka, Flink, stream processing, lakehouse and data engineering — updated nightly.">
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
<header class="top">
  <h1>Streaming <span class="spark">&amp;</span> Data Events</h1>
  <div class="sub">
    Kafka · Flink · stream processing · lakehouse · data engineering &nbsp;·&nbsp;
    <b>{len(events)}</b> events tracked &nbsp;·&nbsp;
    window <b>{win_start.strftime('%b %d')} – {win_end.strftime('%b %d, %Y')}</b> &nbsp;·&nbsp;
    updated <b>{today.strftime('%b %d, %Y')}</b>
  </div>
</header>

<div class="stats">
  <div class="stat"><div class="n">{len(in_window)}</div><div class="l">next 3 months</div></div>
  <div class="stat"><div class="n">{len(cfp_open)}</div><div class="l">CFP open</div></div>
  <div class="stat warn"><div class="n">{len(closing)}</div><div class="l">closing ≤45d</div></div>
  <div class="stat"><div class="n">{len(anchors)}</div><div class="l">flagship</div></div>
</div>

<div class="controls">
  <div class="ctlrow">
    <input id="q" type="search" placeholder="Filter by name, city or source…" aria-label="Filter events">
    <span class="chip cfp" role="button" tabindex="0" aria-pressed="false">CFP open only</span>
    <span class="chip" id="reset" role="button" tabindex="0">reset</span>
  </div>
  <div class="ctlrow"><span class="ctlbl">Topic</span>{chips}</div>
  <div class="ctlrow">{excl_dd}<span id="hiddennote" class="hiddennote"></span></div>
</div>
<div id="noshow" class="empty" style="display:none">Nothing matches those filters.</div>

{sections}

<footer>
  <div>Generated {meta['generated_at']} · next run {e(meta.get('next_run','nightly'))} ·
  {len(events)} events from {len(meta.get('sources', []))} sources.</div>
  <div style="margin-top:8px">Sources:</div>
  <ul>{"".join(f'<li>{e(s)}</li>' for s in meta.get("sources", []))}</ul>
  <div style="margin-top:10px">Dates are taken from each event's own listing; CFP deadlines
  come from the aggregator feeds and first-party pages. Always confirm on the event site
  before submitting a talk.</div>
  {warnbox}
</footer>
</div>
<script type="application/json" id="events-data">{payload}</script>
<script>{JS}</script>
</body>
</html>
"""
