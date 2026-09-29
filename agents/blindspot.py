"""
Blindspot of the day (NF-D2, spec §8.2) — scrape Ground News' Blindspot page (no API, no RSS)
and surface ONE under-covered story with a one-line interpretation: which side of the media
is ignoring it. Max 1/day, skip "thin" days (config blindspot_min_sources). Channel-agnostic:
the SAME pick feeds both the Telegram brief splice and the WhatsApp 11:00 dispatch.

Pure parse/format; fetch() is the only I/O. parse_blindspots() reads the server-rendered HTML
(Ground News embeds each card's "Blindspot: Only X% Left/Right N sources <headline>" text in
the <a href="/article/..."> link). Brittle by nature (a community site's HTML) — so a parse
miss yields NOTHING (the line is simply skipped), never a crash.

    venv\\Scripts\\python.exe agents/blindspot.py            # dry run: fetch + print the pick
    venv\\Scripts\\python.exe tests\\test_blindspot.py
"""
import os
import re

import yaml


def _load_config():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(base_dir, "config", "models.yaml"), "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


try:  # wrapped so a missing/broken config can't break import
    _CFG = _load_config() or {}
except Exception:
    _CFG = {}

BASE_URL = str(_CFG.get("blindspot_base_url", "https://ground.news"))
DEFAULT_URL = BASE_URL + "/blindspot"

# "... Blindspot: Only 13% Left 11 sources US denied Israel's request ..." ->
#   pct=13  side=Left  sources=11  headline="US denied Israel's request ..."
_CARD_RE = re.compile(
    r"Blindspot:\s*(?:Only\s*)?(\d+)%\s*(Left|Right|Center)\s+(\d+)\s+sources?\s+(.+)$",
    re.IGNORECASE,
)


def fetch(url=DEFAULT_URL, timeout=25):
    """The only I/O. Returns the Blindspot page HTML (str)."""
    import requests
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0 (NewsFramer blindspot; personal use)"},
                     timeout=timeout)
    r.raise_for_status()
    return r.text


def _abs_url(href):
    if not href:
        return ""
    return href if href.startswith("http") else BASE_URL + href


def _clean_headline(s):
    s = re.sub(r"\s+", " ", (s or "").strip())
    # cut the trailing Ground News coverage breakdown ("... Left 13 % Center 12 % Right 75 %")
    s = re.split(r"\s+(?:Left|Center|Right)\s+\d+\s*%", s, maxsplit=1)[0].strip()
    # cut trailing cruft (relative time, "Show more") if the card text runs on
    s = re.split(r"\s+(?:\d+\s+(?:hours?|days?|minutes?)\s+ago|Show more)\b", s, maxsplit=1)[0].strip()
    return s[:160].rstrip(" -—,;:")


def parse_blindspots(html):
    """Server-rendered Ground News Blindspot HTML -> [{headline, url, side, pct, sources}].
    Pure. A card that doesn't match the expected shape is skipped (never guessed); deduped by url."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html or "", "html.parser")
    out, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "/article/" not in href and "/story/" not in href:
            continue
        m = _CARD_RE.search(a.get_text(" ", strip=True))
        if not m:
            continue
        url = _abs_url(href)
        if url in seen:
            continue
        headline = _clean_headline(m.group(4))
        if not headline:
            continue
        seen.add(url)
        out.append({"headline": headline, "url": url, "side": m.group(2).capitalize(),
                    "pct": int(m.group(1)), "sources": int(m.group(3))})
    return out


def pick(items, max_items=1, min_sources=0):
    """The day's pick(s): keep stories with >= min_sources (skip 'thin' days), in page order
    (Ground News ranks strongest first), capped at max_items. Pure."""
    strong = [it for it in (items or []) if it.get("sources", 0) >= int(min_sources)]
    return strong[: max(1, int(max_items))] if strong else []


def format_blindspot(items, header, include_link=True):
    """The Blindspot block ('' when none — callers skip cleanly). Pure. *bold*/_italic_ render
    on both Telegram and WhatsApp; the raw URL is clickable on both."""
    if not items:
        return ""
    lines = [header]
    for it in items:
        lines.append(f"*{it['headline']}*")
        lines.append(f"_Under-covered by the {it['side']} — only {it['pct']}% of {it['sources']} sources._")
        if include_link and it.get("url"):
            lines.append(it["url"])
    return "\n".join(lines)


def build(html, max_items=1, min_sources=0, header="🔦 *Blindspot of the Day*", include_link=True):
    """Parse -> pick -> format. '' when nothing qualifies. Pure given html."""
    return format_blindspot(pick(parse_blindspots(html), max_items, min_sources), header, include_link)


def build_from_config(cfg, html=None):
    """Fetch (unless html injected for tests) + build using config knobs. Only I/O is fetch()."""
    cfg = cfg or {}
    if html is None:
        html = fetch(cfg.get("blindspot_url", DEFAULT_URL), int(cfg.get("blindspot_fetch_timeout", 25)))
    return build(html,
                 max_items=int(cfg.get("blindspot_max_items", 1)),
                 min_sources=int(cfg.get("blindspot_min_sources", 5)),
                 header=cfg.get("blindspot_header", "🔦 *Blindspot of the Day*"),
                 include_link=bool(cfg.get("blindspot_include_link", True)))


def splice(brief_text, block):
    """Insert the Blindspot block before the footer rule (---), else append. No block -> text
    unchanged. Mirrors writer.splice_investigations / thread_tracker.splice_what_changed."""
    if not block:
        return brief_text
    marker = "\n---\n"
    idx = brief_text.rfind(marker)
    if idx == -1:
        return brief_text.rstrip() + "\n\n" + block + "\n"
    return brief_text[:idx] + "\n\n" + block + "\n" + brief_text[idx:]


def main():
    import os
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    try:
        import yaml
        cfgp = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "models.yaml")
        with open(cfgp, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    except Exception:
        cfg = {}
    items = parse_blindspots(fetch(cfg.get("blindspot_url", DEFAULT_URL)))
    picked = pick(items, cfg.get("blindspot_max_items", 1), cfg.get("blindspot_min_sources", 5))
    print(f"blindspot: parsed {len(items)} card(s), picked {len(picked)} "
          f"(min_sources={cfg.get('blindspot_min_sources', 5)})")
    print("-" * 60)
    print(build_from_config(cfg) or "(nothing strong today — the line would be skipped)")
    print("-" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
