"""
Briefing character-overrun monitor (spec §15 — "Writer char overrun ~15-17% over cap").

Pure logic, no I/O. The Writer's character cap scales with theme count
(writer_per_theme_chars x themes, clamped floor..ceiling); the LLM does not hard-stop
at that cap, so a brief can run over. This flags an over-cap brief in the run log so a
human (or a log scan) catches editorial drift — it is a QUALITY signal, not a run-health
failure, so callers print the flag and DO NOT change the agent_runs status (the §4.5
watchdog must keep treating an over-cap brief as a successful run).

Also carries the mid-item TRUNCATION safety net (2026-09-04 Serbia-theme bug: a brief
was cut off mid-URL because the model stopped on an output-token/length cap, and the
half-written line shipped as-is). Neither the API path (litellm) nor the subscription
path (`claude -p`, the writer's DEFAULT per config) reliably exposes a trustworthy
finish_reason here, so the defense is a text-shape check: never let the stored brief end
on a line that looks unfinished.

    venv\\Scripts\\python.exe tests\\test_char_monitor.py
"""
import re

# Distinct, greppable marker so a log scan / monitor can match on it.
OVERRUN_MARKER = "⚠ CHAR OVERRUN"
TRUNCATION_MARKER = "⚠ TRUNCATED OUTPUT"

# A "complete" trailing line ends in sentence punctuation, a closing quote/paren (covers
# a closed Markdown link '...(url)' and '**Articles:**'), or a closing bold/italic marker.
# Japanese (。！？」』）) and Urdu (۔ ؟) sentence endings count too, so a ja/ur brief is never trimmed.
_COMPLETE_END = re.compile(r'(?:[.!?”")。！？」』）۔؟…]|\*\*|_)\s*$')
# Headings and the '---' footer rule are always "complete" regardless of trailing char.
_OK_LINE = re.compile(r'^\s*(#{1,6}\s|-{3,}\s*$)')


def strip_incomplete_tail(text, max_strip=5):
    """Drop trailing line(s) that look CUT OFF mid-item (mid-sentence, mid-URL, mid-link)
    so a truncated LLM response never ships with a dangling half-written item. Trailing
    blank lines are dropped for free (not counted). Walks backward from the end and stops
    at the first line that looks complete; `max_strip` bounds how much it will remove so a
    false-positive tail scan can never eat the whole brief. Returns (clean_text,
    stripped_count) — stripped_count > 0 means something WAS cut and the caller should
    flag it (see `truncation_flag`). Pure; tolerant of falsy/non-string input."""
    if not text:
        return text, 0
    try:
        lines = str(text).split("\n")
    except Exception:
        return text, 0
    while lines and lines[-1].strip() == "":
        lines.pop()
    stripped = 0
    while lines and stripped < max_strip:
        last = lines[-1]
        if _OK_LINE.match(last) or _COMPLETE_END.search(last.rstrip()):
            break
        lines.pop()
        stripped += 1
    return "\n".join(lines).rstrip("\n"), stripped


def truncation_flag(stripped_count):
    """One-line flag when strip_incomplete_tail actually removed something, else None."""
    try:
        stripped_count = int(stripped_count)
    except (TypeError, ValueError):
        return None
    if stripped_count <= 0:
        return None
    return (f"{TRUNCATION_MARKER}: brief was cut off mid-item — {stripped_count} incomplete "
            f"trailing line(s) removed before storing (model likely hit an output-token/length cap).")


def overrun_flag(text_len, max_chars, warn_ratio=1.0):
    """Return a one-line overrun flag string when a brief exceeds its cap, else None.

    text_len   : length of the produced briefing (characters).
    max_chars  : the theme-scaled cap the brief was generated against.
    warn_ratio : tolerance multiplier applied to the cap before comparison.
                 1.0 flags ANY overrun; 1.15 flags only > 15% over. Defaults to 1.0
                 so the default behaviour is "flag every over-cap brief".

    Returns None (no flag) when within the tolerance, or when inputs are unusable
    (non-numeric, or max_chars <= 0) — a monitor must never crash the brief.
    The reported overrun (+chars, +pct) is measured against the cap itself, not the
    tolerance threshold, so the number a human reads is the true overrun vs cap.
    """
    try:
        text_len = int(text_len)
        max_chars = int(max_chars)
        warn_ratio = float(warn_ratio)
    except (TypeError, ValueError):
        return None
    if max_chars <= 0:
        return None
    if text_len <= max_chars * warn_ratio:
        return None
    over = text_len - max_chars
    pct = (over / max_chars) * 100.0
    return f"{OVERRUN_MARKER}: {text_len} chars > cap {max_chars} (+{over}, +{pct:.1f}%)"
