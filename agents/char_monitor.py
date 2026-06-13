"""
Briefing character-overrun monitor (spec §15 — "Writer char overrun ~15-17% over cap").

Pure logic, no I/O. The Writer's character cap scales with theme count
(writer_per_theme_chars x themes, clamped floor..ceiling); the LLM does not hard-stop
at that cap, so a brief can run over. This flags an over-cap brief in the run log so a
human (or a log scan) catches editorial drift — it is a QUALITY signal, not a run-health
failure, so callers print the flag and DO NOT change the agent_runs status (the §4.5
watchdog must keep treating an over-cap brief as a successful run).

    venv\\Scripts\\python.exe tests\\test_char_monitor.py
"""

# Distinct, greppable marker so a log scan / monitor can match on it.
OVERRUN_MARKER = "⚠ CHAR OVERRUN"


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
