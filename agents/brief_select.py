"""
Which briefing to deliver (NF-F4 — wrong-brief-delivered bug).

Pure logic, no I/O. `deliver_brief.py` previously sent the LATEST briefing by
created_at. That let a stray second generator (the legacy Cloud Run container,
which dates briefs in UTC and is starved by the §4.3 set-difference because the
real brief already recorded the day's articles) win purely on recency — so the
thin, lower-quality brief reached Telegram while the complete one was shadowed.

This picks **today's (JST) most-COMPLETE fresh brief** instead:
  1. drop empty-content and stale (age > fresh_hours) briefs,
  2. prefer briefs whose `date` == today's JST date (the stray is dated in UTC,
     i.e. yesterday at the 06:00 JST run, so this excludes it outright),
  3. among those, take the longest body (completeness tie-break — guards the case
     where a stray ever shares today's date).

    venv\\Scripts\\python.exe tests\\test_brief_select.py
"""
from datetime import datetime


def _age_hours(created, now_utc):
    """Hours between a brief's created_at (ISO string) and now_utc. None if unparseable
    (caller treats None as 'do not exclude on freshness alone', matching prior leniency)."""
    if not created:
        return None
    try:
        ts = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
        return (now_utc - ts).total_seconds() / 3600.0
    except Exception:
        return None


def pick_best_brief(rows, today_jst, fresh_hours, lang_col, now_utc):
    """Choose the brief to deliver from recent briefings (newest-first or any order).

    rows       : list of briefing dicts with at least {created_at, date, <lang_col>}.
    today_jst  : today's date in JST as 'YYYY-MM-DD' (string, matches the stored `date`).
    fresh_hours: max age; older briefs are not delivered.
    lang_col   : the content column to read/measure (e.g. 'content_en').
    now_utc    : timezone-aware 'now' (injected so this stays pure/testable).

    Returns (chosen_row, None) or (None, reason).
    """
    fresh = []
    for row in rows or []:
        body = (row.get(lang_col) or "").strip()
        if not body:
            continue
        age = _age_hours(row.get("created_at"), now_utc)
        if age is not None and age > fresh_hours:
            continue
        fresh.append(row)

    if not fresh:
        return None, "no fresh non-empty brief"

    todays = [r for r in fresh if r.get("date") == today_jst]
    pool = todays or fresh  # fall back to any fresh brief rather than deliver nothing
    best = max(pool, key=lambda r: len((r.get(lang_col) or "")))
    return best, None
