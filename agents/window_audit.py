"""
Window-span audit (NF-NEW2 — "each session's content provably spans ~24h").

Pure logic, no I/O. Both daily sessions load articles with `published_at >= now - window_hours`
(a true 24h-by-publication-time window). This summarises the ACTUAL span of the loaded set so
every run PROVES, in its own log, how far back it reached and how fresh its newest item is —
turning "is the window really 24h?" from a guess into a printed fact, checkable against the DB.

Log-only (same shape as the NF-F2 char flag): never alters or blocks a brief; tolerant of
blank/odd timestamps (skipped, never raises).

    venv\\Scripts\\python.exe tests\\test_window_audit.py
"""
from datetime import datetime, timezone, timedelta

WINDOW_MARKER = "WINDOW"


def _parse(p):
    """ISO timestamp -> aware UTC datetime, or None. Naive timestamps are assumed UTC."""
    if not p:
        return None
    try:
        dt = datetime.fromisoformat(str(p).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def window_span(published_ats, now, fresh_hours=6):
    """Return facts about the loaded in-window set: (count, oldest_age_h, newest_age_h, fresh_count).
    oldest/newest are hours BEFORE `now`; fresh_count = items <= fresh_hours old. Empty/all-bad
    input -> (0, None, None, 0). Pure; tolerant."""
    ages = []
    for p in (published_ats or []):
        dt = _parse(p)
        if dt is None:
            continue
        ages.append((now - dt).total_seconds() / 3600.0)
    if not ages:
        return (0, None, None, 0)
    fresh = sum(1 for a in ages if a <= fresh_hours)
    return (len(ages), max(ages), min(ages), fresh)


def window_span_report(published_ats, window_hours, now, fresh_hours=6, label="WINDOW"):
    """One-line, greppable proof of the window a run actually used. Shows the cutoff (= now -
    window_hours) and the real span of the loaded set. Pure; never raises."""
    try:
        wh = float(window_hours)
    except (TypeError, ValueError):
        wh = 24.0
    cutoff = now - timedelta(hours=wh)
    n, oldest, newest, fresh = window_span(published_ats, now, fresh_hours)
    head = f"{label}: {wh:.1f}h (cutoff {cutoff.strftime('%Y-%m-%d %H:%M UTC')}); in-window {n}"
    if n == 0:
        return head
    return (f"{head}; oldest {oldest:.1f}h, newest {newest:.1f}h, "
            f"fresh(<{int(fresh_hours)}h) {fresh}")
