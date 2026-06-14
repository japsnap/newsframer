"""
Drop-report feature — pure logic (spec 8.5, basic version).

A "drop-report" is an article from an investigative source (category =
'investigative'). It always surfaces as a SPECIAL high-visibility highlight in
its own "Investigations" section, and is ALSO woven into the day's main theme
when it semantically matches it. Expandable on request via a short/long pair.

This module holds only the deterministic, side-effect-free pieces so they can be
unit-tested without a DB or LLM. DB selection, LLM summary generation, and
persistence live in writer.py (Telegram-self path only) and the JSON store.
"""
import re

INVESTIGATIONS_HEADER = "## 🔍 Investigations"
_SLUG_MAX = 40
_SLUG_WORDS = 4


def make_slug(title, existing=None):
    """Short, memorable, URL-safe key for the 'reply more: <slug>' UX.

    First few significant words of the title, lowercased, ascii alnum + hyphen.
    Falls back to 'drop' for empty/garbage titles. De-duplicates against
    `existing` (a set/collection of already-used slugs) by appending -2, -3, ...
    """
    words = re.findall(r"[a-z0-9]+", (title or "").lower())
    base = "-".join(words[:_SLUG_WORDS])[:_SLUG_MAX].strip("-")
    if not base:
        base = "drop"
    existing = set(existing or ())
    if base not in existing:
        return base
    n = 2
    while f"{base}-{n}" in existing:
        n += 1
    return f"{base}-{n}"


def is_woven(drop_topics, main_topics, min_shared=1):
    """True if the drop shares >= min_shared analyst topics with the day's main
    theme (themes[0]). Empty on either side -> not woven (stands alone)."""
    d = {t for t in (drop_topics or []) if t}
    m = {t for t in (main_topics or []) if t}
    if not d or not m:
        return False
    return len(d & m) >= min_shared


def pick_diverse(ordered, max_drops, max_per_source, source_key):
    """From a list already sorted best-first, choose up to max_drops items while
    taking at most max_per_source from any single source — so one high-volume source
    can't monopolise the Investigations section (the "3x same source" bug, e.g. three
    Middle East Eye live-blog items). If too few distinct sources exist to fill
    max_drops, backfill with the best remaining items (still best-first).
    source_key(item) returns the item's source identity (e.g. its source_id)."""
    chosen, over_cap, per = [], [], {}
    for item in ordered or []:
        src = source_key(item)
        if per.get(src, 0) < max_per_source:
            chosen.append(item)
            per[src] = per.get(src, 0) + 1
            if len(chosen) >= max_drops:
                return chosen
        else:
            over_cap.append(item)
    for item in over_cap:          # only when too few distinct sources to fill the cap
        if len(chosen) >= max_drops:
            break
        chosen.append(item)
    return chosen[:max_drops]


def render_investigations_section(drops):
    """Deterministic Markdown for the Investigations section. Built in Python (not
    by the LLM) so it can't be dropped/hallucinated and never leaks into the
    WhatsApp path. `drops` items: {title, short, source, url, slug}. Empty -> ''.
    """
    if not drops:
        return ""
    lines = [INVESTIGATIONS_HEADER, ""]
    for d in drops:
        title = d.get("title", "").strip()
        short = (d.get("short") or "").strip()
        source = d.get("source", "Unknown")
        url = d.get("url", "")
        slug = d.get("slug", "")
        lines.append(f"🔍 **{title}** — {short} [{source}]({url})")
        lines.append(f'_Investigation · reply "more: {slug}" for the full write-up._')
        lines.append("")
    return "\n".join(lines).rstrip()


def splice_investigations(briefing_text, section_md):
    """Insert the Investigations section above '## Highlights' (or, if there is no
    Highlights section, above the footer '---' line; else append). Empty section
    -> text unchanged."""
    if not section_md:
        return briefing_text
    block = section_md.rstrip() + "\n\n"

    idx = briefing_text.find("## Highlights")
    if idx != -1:
        return briefing_text[:idx] + block + briefing_text[idx:]

    # Footer is a line that is exactly '---' (the format_rules separator).
    m = re.search(r"^---\s*$", briefing_text, re.MULTILINE)
    if m:
        return briefing_text[:m.start()] + block + briefing_text[m.start():]

    return briefing_text.rstrip() + "\n\n" + section_md.rstrip()
