"""
Highlight tense/certainty monitor (2026-09-05 bug: a highlight said Anthropic "completed
a $2 trillion IPO" when the source said it "could seek" that valuation in a PLANNED
October offering — the Writer upgraded a hedged, future claim into a completed fact).

Pure keyword logic, no I/O, no LLM. This can only ever be a heuristic — real tense/
certainty detection needs language understanding the Writer itself provides (see the
prompt-level fix in prompts/writer/format_rules.txt) — so this is a SAFETY NET, not the
fix: it flags a highlight whose SOURCE material (title/differentiator/reasoning/content
snippet, i.e. exactly what the Writer was given) reads as hedged/uncertain but whose
FINAL rendered bullet asserts the same thing as a done deal. Log-only, like
char_monitor/link_monitor: never rewrites or blocks the brief.

    venv\\Scripts\\python.exe tests\\test_tense_monitor.py
"""
import re

TENSE_MISMATCH_MARKER = "⚠ TENSE MISMATCH"

# Hedged / not-yet-certain language a source uses for something planned, rumored, or in
# progress. Matched as plain substrings against lowercased text — deliberately generous
# (a false positive here just adds a flag for a human to glance at; a miss ships the bug).
HEDGE_PHRASES = [
    "could", "may ", "might", "plans to", "planning to", "plans a", "planned",
    "is seeking", "seeking to", "reportedly", "is expected", "expected to",
    "considering", "in talks", "weighing", "rumored", "said to be", "is exploring",
    "exploring a", "is set to", "aims to", "intends to", "proposed", "potential",
    "would ", "is reportedly", "sources say", "eyeing", "in the works",
]

# Language that states the SAME kind of action as a finished, certain fact.
DONE_DEAL_PHRASES = [
    "completed", "has completed", "closed", "has closed", "finalized", "has finalized",
    "secured", "has secured", "confirmed", "has confirmed", "signed", "has signed",
    "has agreed", "announced the completion", "officially",
]


def _norm(s):
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def source_is_hedged(*texts):
    """True if ANY given source text contains a hedging/uncertainty phrase."""
    blob = _norm(" ".join(t for t in texts if t))
    return any(h in blob for h in HEDGE_PHRASES)


def bullet_is_done_deal(bullet_text):
    """True if the rendered bullet states the action as a completed, certain fact."""
    blob = _norm(bullet_text)
    return any(d in blob for d in DONE_DEAL_PHRASES)


def _bullet_line_for_url(briefing_text, url):
    """The single line in briefing_text that renders the citation for `url`, or None.
    Matches on '](url)' — the Writer's canonical Markdown-link shape — so the line found
    is provably the SAME highlight the caller is checking, not just any nearby text."""
    if not url:
        return None
    needle = f"]({url})"
    for line in (briefing_text or "").split("\n"):
        if needle in line:
            return line
    return None


def find_tense_mismatches(highlights, briefing_text):
    """highlights: the ORIGINAL list the Writer was given for the ## Highlights section
    (each a dict with 'title', 'url', 'content_raw', and 'score' holding
    'differentiator'/'reasoning' — exactly writer.pick_highlights' output). briefing_text:
    the FINAL rendered brief. Returns a list of {"title", "url", "reason"} for any
    highlight whose source material was hedged/uncertain but whose rendered bullet
    asserts it as done. A highlight is matched to its bullet by URL, so unrelated bullets
    are never compared. Pure; tolerant of missing fields."""
    out = []
    for h in highlights or []:
        url = h.get("url") or ""
        line = _bullet_line_for_url(briefing_text, url)
        if not line:
            continue
        s = h.get("score") or {}
        source_blob = " ".join([
            h.get("title") or "",
            s.get("differentiator") or "",
            s.get("reasoning") or "",
            (h.get("content_raw") or "")[:1000],
        ])
        if source_is_hedged(source_blob) and bullet_is_done_deal(line):
            out.append({
                "title": h.get("title") or "",
                "url": url,
                "reason": "source material reads as hedged/uncertain (plans, could, "
                          "reportedly, ...) but the highlight states it as a completed fact",
            })
    return out


def tense_mismatch_flag(highlights, briefing_text):
    """One-line flag summarizing find_tense_mismatches(), or None when clean."""
    mismatches = find_tense_mismatches(highlights, briefing_text)
    if not mismatches:
        return None
    titles = "; ".join(m["title"][:70] for m in mismatches[:3])
    more = f" (+{len(mismatches) - 3} more)" if len(mismatches) > 3 else ""
    return f"{TENSE_MISMATCH_MARKER}: {len(mismatches)} highlight(s) may overstate certainty: {titles}{more}"
