"""
Event-feed digest (NF-A2) — a self-contained RSS-headline digest delivered as its OWN
WhatsApp message, isolated from the main brief: NO LLM, NO DB writes, NO writer/litellm
import. Football is the first instance; this module is deliberately TOPIC-AGNOSTIC so it
can be re-used as a template for other events after the World Cup — the feeds, header,
window and caps are all passed in (sourced from config/models.yaml by the runner).

Pure parse/format; fetch() is the only I/O. Anti-empty: build_message() returns '' when no
items fall in the window, so the runner skips the send (never an empty WhatsApp message).

    venv\\Scripts\\python.exe tests\\test_event_feed.py
"""
import re
import time
from datetime import datetime, timezone, timedelta


# --- I/O (the only side effect) -------------------------------------------
def fetch(url, timeout=25):
    """GET a feed's XML. Raises on network/HTTP error (the caller wraps per-feed so one dead
    feed can't sink the digest)."""
    import requests
    r = requests.get(url, headers={"User-Agent": "NewsFramer/1.0 (event digest; personal use)"},
                     timeout=timeout)
    r.raise_for_status()
    return r.text


# --- pure helpers ----------------------------------------------------------
def _entry_dt(entry):
    """An entry's publish time as tz-aware UTC, or None if absent/unparseable."""
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            try:
                return datetime.fromtimestamp(time.mktime(t), tz=timezone.utc)
            except Exception:
                pass
    return None


def parse_feed(xml_text, source_name):
    """RSS/Atom text -> [{title, link, source, published(UTC|None)}]. Pure (feedparser)."""
    import feedparser
    parsed = feedparser.parse(xml_text or "")
    out = []
    for e in parsed.entries:
        title = (e.get("title") or "").strip()
        if not title:
            continue
        out.append({
            "title": title,
            "link": (e.get("link") or "").strip(),
            "source": source_name,
            "published": _entry_dt(e),
        })
    return out


def within_window(items, now_utc, window_hours):
    """Keep items published within window_hours. Undated items are KEPT (can't prove stale)
    but sort last in cap()."""
    cutoff = now_utc - timedelta(hours=int(window_hours))
    return [it for it in items if it.get("published") is None or it["published"] >= cutoff]


def _norm_title(title):
    return re.sub(r"\s+", " ", (title or "").lower()).strip()


def dedup(items):
    """Drop repeated headlines (same normalized title), keeping first seen. Pure."""
    seen, out = set(), []
    for it in items:
        key = _norm_title(it.get("title"))
        if key and key not in seen:
            seen.add(key)
            out.append(it)
    return out


_EPOCH = datetime.min.replace(tzinfo=timezone.utc)


def cap(items, max_total, max_per_source):
    """Newest-first, at most max_per_source per feed, at most max_total overall. Pure."""
    ordered = sorted(items,
                     key=lambda it: (it.get("published") is not None, it.get("published") or _EPOCH),
                     reverse=True)
    per, out = {}, []
    for it in ordered:
        s = it.get("source")
        if per.get(s, 0) >= int(max_per_source):
            continue
        per[s] = per.get(s, 0) + 1
        out.append(it)
        if len(out) >= int(max_total):
            break
    return out


def format_digest(items, header, include_links=True, reply_line=""):
    """WhatsApp message string from the capped items. '' when there are none. Pure."""
    if not items:
        return ""
    lines = [header, ""]
    for it in items:
        lines.append(f"• {it['title']}")
        if include_links and it.get("link"):
            lines.append(f"  _{it['source']}_ — {it['link']}")
        else:
            lines.append(f"  _{it['source']}_")
    if reply_line:
        lines += ["", reply_line]
    return "\n".join(lines)


def build_message(feeds_data, now_utc, window_hours, max_items, max_per_source,
                  header, include_links=True, reply_line=""):
    """feeds_data: [(source_name, xml_text)] -> the WhatsApp digest ('' if nothing in window).
    Parse-time errors on one feed drop that feed only. Pure given the fetched feeds_data."""
    items = []
    for name, xml in feeds_data or []:
        try:
            items += parse_feed(xml, name)
        except Exception:
            continue
    items = within_window(items, now_utc, window_hours)
    items = dedup(items)
    items = cap(items, max_items, max_per_source)
    return format_digest(items, header, include_links, reply_line)
