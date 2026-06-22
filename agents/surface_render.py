"""Per-surface output rendering — items 1, 2, 3, 5 of the 2026-06-19 output-fixes work order.

PURE + fully config-driven; a future settings UI reads the SAME config keys. NOTHING is
hard-coded here — every number/threshold/flag is passed in from config/models.yaml with a
default that reproduces today's behaviour. Reused by the Telegram writer + delivery and the
WhatsApp brief, so Telegram and WhatsApp are tuned INDEPENDENTLY.

What lives here:
  - item 1: per-theme SIZE levels (S/M/L) -> a multiplier on the writer_* char caps, per surface.
  - item 2: per-surface LINK/SOURCE display (show_source / include_link / link_style) -> a
            deterministic rewrite of the writer's canonical citation lines, + headings->bold.
  - item 3: highlight de-duplication (same event by cluster_id, and same identical topic-set).
  - item 5: WhatsApp topic EXCLUDE filter (drop crypto/markets leaks even when an include
            keyword matched), per category, registry-overridable.

The writer emits two canonical citation shapes (see prompts/writer/format_rules.txt):
  theme article:  "[N] <title> — [<source>](<url>)"
  highlight:      "- **<title>** — <summary> [<source>](<url>)"
"""
import re

# em / en dash or hyphen, with surrounding spaces — the writer uses an em dash.
_DASH = r"[—–-]"
_THEME_CITE = re.compile(r"^(\s*)\[(\d+)\]\s+(.*?)\s+" + _DASH + r"\s+\[([^\]]+)\]\((https?://[^)\s]+)\)\s*$")
_HL_CITE = re.compile(r"^(\s*)-\s+\*\*(.+?)\*\*\s*" + _DASH + r"\s*(.*?)\s*\[([^\]]+)\]\((https?://[^)\s]+)\)\s*$")
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")


# ============================================================================
# item 1/2/3 — per-theme SIZE as ONE control (absolute per-theme char TARGET)
# ============================================================================
_DEFAULT_SIZE_TARGETS = {"S": 1000, "M": 2000, "L": 4000}


def resolve_size_level(config, surface, chat_length=None):
    """The size level (S/M/L) for a surface. A per-chat `length` (short/medium/long) maps via
    config['length_to_size'] (item 3) and WINS when given; else the surface's `theme_size`; default
    'M'. Unknown values fall back to 'M'."""
    levels = config.get("theme_size_levels") or _DEFAULT_SIZE_TARGETS
    if chat_length:
        mapped = (config.get("length_to_size") or {"short": "S", "medium": "M", "long": "L"}).get(chat_length)
        if mapped:
            return mapped if mapped in levels else "M"
    lvl = ((config.get("surfaces") or {}).get(surface) or {}).get("theme_size", "M")
    return lvl if lvl in levels else "M"


def per_theme_target(config, level):
    """The ABSOLUTE per-theme char TARGET for a level — the writer is told to WRITE each theme to
    ~this length (not just stay under a ceiling, which the LLM underfilled). Missing/unknown -> M."""
    levels = config.get("theme_size_levels") or _DEFAULT_SIZE_TARGETS
    try:
        return int(levels.get(level, levels.get("M", 2000)))
    except (TypeError, ValueError):
        return int(_DEFAULT_SIZE_TARGETS["M"])


def derive_cap(target, num_themes, highlights_count=0, per_highlight_chars=250, per_theme_source_chars=0):
    """item 2 (body-based): the TOTAL char cap is DERIVED, never a separate number. `target` is the
    per-theme BODY (synthesis prose, EXCLUDING the Articles/source list); the per-theme source list is
    added as its OWN allowance so the SIZE level depends on the body only:
        cap = (body_target + per_theme_source_chars) x #themes + highlights_count x per_highlight_chars
    Pure."""
    return ((int(target) + max(0, int(per_theme_source_chars))) * max(0, int(num_themes))
            + max(0, int(highlights_count)) * max(0, int(per_highlight_chars)))


# ============================================================================
# item 2 — per-surface link / source display
# ============================================================================
def link_cfg(config, surface):
    """Resolve the link/source knobs for a surface. Defaults: source ON; Telegram links ON
    (hyperlink), WhatsApp links OFF."""
    surf = (config.get("surfaces") or {}).get(surface) or {}
    return {
        "show_source": bool(surf.get("show_source", True)),
        "include_link": bool(surf.get("include_link", surface == "telegram")),
        "link_style": str(surf.get("link_style", "hyperlink")),
    }


def _render_source(source, url, cfg):
    """The trailing source/link fragment for one citation, per the surface's link cfg."""
    if cfg["include_link"]:
        if cfg["link_style"] == "plain":            # show the raw URL as text (auto-linked)
            return f"{source} {url}" if cfg["show_source"] else url
        return f"[{source}]({url})"                  # hyperlink: clickable source NAME, URL hidden
    return source if cfg["show_source"] else ""       # no link: plain source name (or nothing)


def render_citations(text, cfg, number_style="dot"):
    """Rewrite the writer's canonical citation lines per the surface link cfg. Non-citation
    lines pass through untouched.
      theme article '[N] <title> — [src](url)' -> '<num><title> — <src-fragment>'
      highlight     '- **t** — summary [src](url)' -> '- **t** — summary <src-fragment>'
    number_style: 'dot' -> 'N. '  (keeps the footnote number, drops the [ ] that collide with
    the real link and trip Telegram's HTML->plain-text fallback); 'none' -> no leading number.
    """
    out = []
    for line in text.split("\n"):
        m = _THEME_CITE.match(line)
        if m:
            indent, n, title, source, url = m.groups()
            num = "" if number_style == "none" else f"{n}. "
            src = _render_source(source, url, cfg)
            sep = " — " if src else ""
            out.append(f"{indent}{num}{title}{sep}{src}".rstrip())
            continue
        m = _HL_CITE.match(line)
        if m:
            indent, title, summary, source, url = m.groups()
            src = _render_source(source, url, cfg)
            tail = f" {src}" if src else ""
            out.append(f"{indent}- **{title}** — {summary.strip()}{tail}".rstrip())
            continue
        out.append(line)
    return "\n".join(out)


def headings_to_bold(text, marker="**"):
    """Convert Markdown headings (#..######) to inline bold for channels with no heading
    concept (Telegram = '**', WhatsApp '*'). Keeps any leading emoji in the heading text."""
    out = []
    for line in text.split("\n"):
        m = _HEADING.match(line)
        out.append(f"{marker}{m.group(2).strip()}{marker}" if m else line)
    return "\n".join(out)


def render_for_telegram(text, config):
    """Full Telegram render: clean citations (clickable source, no visible URL) + headings->bold,
    so the gateway emits valid Telegram HTML (clickable source names) instead of falling back to
    plain text where a link flattens to 'Source (URL)'. Driven entirely by config['surfaces']['telegram']."""
    cfg = link_cfg(config, "telegram")
    return headings_to_bold(render_citations(text, cfg, number_style="dot"), marker="**")


# ============================================================================
# item 3 — highlight de-duplication (same event / same identical topic-set)
# ============================================================================
def _topics_of(article):
    sc = article.get("score") or {}
    return set(sc.get("topics") or [])


def _jaccard(a, b):
    if not a and not b:
        return 0.0
    u = a | b
    return (len(a & b) / len(u)) if u else 0.0


def dedupe_highlights(highlights, theme_articles=None, *, by_cluster=True,
                      topic_overlap=1.0, min_shared_topics=3):
    """Collapse repetitive highlights so the SAME event/topic is not shown several times.
    Input order is preserved and is assumed highest-relevance-first, so the kept representative
    is the strongest one. Pure.
      1. drop a highlight whose cluster_id already appears among theme_articles (theme<->highlight).
      2. among the rest, keep ONE per cluster_id (when by_cluster).
      3. and keep ONE per near-identical topic-set: Jaccard(topics) >= topic_overlap AND
         >= min_shared_topics topics in common (so only rich, genuinely-same signatures collapse;
         thin 1-2 tag overlaps never do).
    topic_overlap >= 1.0 => collapse only IDENTICAL topic-sets."""
    theme_clusters = {a.get("cluster_id") for a in (theme_articles or []) if a.get("cluster_id") is not None}
    kept, kept_clusters, kept_topicsets = [], set(), []
    for h in highlights:
        cid = h.get("cluster_id")
        if cid is not None and cid in theme_clusters:
            continue
        if by_cluster and cid is not None and cid in kept_clusters:
            continue
        ts = _topics_of(h)
        if any(len(ts & kts) >= min_shared_topics and _jaccard(ts, kts) >= topic_overlap
               for kts in kept_topicsets):
            continue
        kept.append(h)
        if cid is not None:
            kept_clusters.add(cid)
        if ts:
            kept_topicsets.append(ts)
    return kept


# ============================================================================
# item 5 — WhatsApp topic EXCLUDE filter (negative filter on top of the include match)
# ============================================================================
def passes_topic_filter(topics, categories, include_keywords, exclude_keywords=None):
    """A story is KEPT for a surface if SOME selected category includes it (an include keyword
    is a substring of its analyst topics) AND that same category does NOT exclude it. The
    exclude list is per-category (plus an optional '*' that applies to every category), so e.g.
    crypto/markets stories tagged 'geopolitics affecting markets' are dropped from geopolitics
    while a crypto-stealing-MALWARE story still passes via cybersecurity (which lists no excludes).
    exclude_keywords None/{} => no exclusions => today's include-only behaviour."""
    blob = " ".join(topics or []).lower()
    exclude_keywords = exclude_keywords or {}
    star = [str(k).lower() for k in exclude_keywords.get("*", [])]
    for cat in categories:
        inc = include_keywords.get(cat, [cat])
        if any(str(k).lower() in blob for k in inc):
            exc = [str(k).lower() for k in exclude_keywords.get(cat, [])] + star
            if not any(k in blob for k in exc):
                return True
    return False
