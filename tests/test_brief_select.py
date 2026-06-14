"""
Tests for agents/brief_select.py — which briefing gets delivered (NF-F4).

Reproduces the real bug: a stray legacy-Cloud-Run brief, dated in UTC (= yesterday
in JST) and starved thin by §4.3, is created ~90s AFTER the real brief. Delivery
used to take the latest-by-created_at and send the thin stray. pick_best_brief must
instead return today's (JST) most-complete fresh brief.

    venv\\Scripts\\python.exe tests\\test_brief_select.py
"""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
import brief_select as bs  # noqa: E402

PASS = []


def ok(name, cond):
    if not cond:
        raise AssertionError(name)
    PASS.append(name)


# Delivery fires ~06:10 JST on 2026-06-13 == 2026-06-12 21:10 UTC.
NOW = datetime(2026, 6, 12, 21, 10, 0, tzinfo=timezone.utc)
TODAY_JST = "2026-06-13"
FRESH = 20.0
COL = "content_en"


def brief(id, date, created_utc, chars):
    return {"id": id, "date": date, "created_at": created_utc, COL: "x" * chars}


# The real brief (06:07 JST, today-dated, complete) and the stray (06:08 JST, UTC-dated, thin).
REAL = brief("real", "2026-06-13", "2026-06-12T21:07:21+00:00", 17226)
STRAY = brief("stray", "2026-06-12", "2026-06-12T21:08:54+00:00", 6518)


def test_the_bug_picks_real_not_latest_stray():
    # rows newest-first, as the query returns them: stray is newest.
    chosen, why = bs.pick_best_brief([STRAY, REAL], TODAY_JST, FRESH, COL, NOW)
    ok("bug_no_reason", why is None)
    ok("bug_picks_real", chosen is not None and chosen["id"] == "real")
    ok("bug_not_stray", chosen["id"] != "stray")


def test_today_date_beats_a_longer_older_nontoday_brief():
    # today's brief is SHORTER, yesterday's is LONGER but wrong day -> today still wins.
    today_thin = brief("today_thin", "2026-06-13", "2026-06-12T21:07:00+00:00", 5000)
    yday_long = brief("yday_long", "2026-06-12", "2026-06-12T21:08:00+00:00", 20000)
    chosen, _ = bs.pick_best_brief([yday_long, today_thin], TODAY_JST, FRESH, COL, NOW)
    ok("date_beats_length", chosen["id"] == "today_thin")


def test_tiebreak_longest_among_todays():
    a = brief("today_a", "2026-06-13", "2026-06-12T21:00:00+00:00", 8000)
    b = brief("today_b", "2026-06-13", "2026-06-12T21:05:00+00:00", 17000)
    chosen, _ = bs.pick_best_brief([b, a], TODAY_JST, FRESH, COL, NOW)
    ok("tiebreak_longest", chosen["id"] == "today_b")


def test_stale_today_brief_excluded():
    stale = brief("stale", "2026-06-13", "2026-06-11T00:00:00+00:00", 17000)  # ~45h old
    chosen, why = bs.pick_best_brief([stale], TODAY_JST, FRESH, COL, NOW)
    ok("stale_none", chosen is None)
    ok("stale_reason", why is not None)


def test_empty_today_falls_back_to_fresh_nonempty():
    empty_today = brief("empty", "2026-06-13", "2026-06-12T21:07:00+00:00", 0)
    yday_fresh = brief("yday", "2026-06-12", "2026-06-12T21:06:00+00:00", 9000)
    chosen, _ = bs.pick_best_brief([empty_today, yday_fresh], TODAY_JST, FRESH, COL, NOW)
    ok("empty_excluded", chosen is not None and chosen["id"] == "yday")


def test_unparseable_created_at_not_excluded_on_freshness():
    weird = brief("weird", "2026-06-13", "not-a-timestamp", 12000)
    chosen, _ = bs.pick_best_brief([weird], TODAY_JST, FRESH, COL, NOW)
    ok("unparseable_kept", chosen is not None and chosen["id"] == "weird")


def test_no_rows_and_all_empty_return_reason():
    none_chosen, why1 = bs.pick_best_brief([], TODAY_JST, FRESH, COL, NOW)
    ok("empty_rows_none", none_chosen is None and why1 is not None)
    allempty = [brief("e1", "2026-06-13", "2026-06-12T21:07:00+00:00", 0)]
    none2, why2 = bs.pick_best_brief(allempty, TODAY_JST, FRESH, COL, NOW)
    ok("all_empty_none", none2 is None and why2 is not None)


def main():
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
            except AssertionError as e:
                print(f"FAIL: {e}")
                failed += 1
            except Exception as e:
                print(f"ERROR in {name}: {type(e).__name__}: {e}")
                failed += 1
    print(f"\n{len(PASS)} checks passed, {failed} test(s) failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
