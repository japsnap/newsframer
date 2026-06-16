"""
Tests for agents/window_audit.py (NF-NEW2) — pure window-span reporting. No DB, no LLM.

Proves each session can print, and we can assert, the real published_at span of its loaded
in-window set (so "is it really 24h?" is a checkable fact, not a guess).

    venv\\Scripts\\python.exe tests\\test_window_audit.py
"""
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
import window_audit as wa  # noqa: E402

PASS = []
NOW = datetime(2026, 6, 16, 2, 0, 0, tzinfo=timezone.utc)  # 11:00 JST


def ok(name, cond):
    if not cond:
        raise AssertionError(name)
    PASS.append(name)


def ago(h):
    return (NOW - timedelta(hours=h)).isoformat()


# --- window_span ----------------------------------------------------------
def test_span_basic():
    n, oldest, newest, fresh = wa.window_span([ago(23), ago(5), ago(1)], NOW, fresh_hours=6)
    ok("count", n == 3)
    ok("oldest", abs(oldest - 23.0) < 0.01)
    ok("newest", abs(newest - 1.0) < 0.01)
    ok("fresh_two", fresh == 2)  # 5h and 1h are <=6h; 23h is not


def test_span_empty():
    ok("empty", wa.window_span([], NOW) == (0, None, None, 0))
    ok("all_bad", wa.window_span(["", None, "not-a-date"], NOW) == (0, None, None, 0))


def test_span_naive_assumed_utc():
    naive = (NOW.replace(tzinfo=None) - timedelta(hours=10)).isoformat()
    n, oldest, _, _ = wa.window_span([naive], NOW)
    ok("naive_utc", n == 1 and abs(oldest - 10.0) < 0.01)


def test_span_handles_zulu():
    z = (NOW - timedelta(hours=12)).strftime("%Y-%m-%dT%H:%M:%SZ")
    n, oldest, _, _ = wa.window_span([z], NOW)
    ok("zulu", n == 1 and abs(oldest - 12.0) < 0.01)


def test_span_skips_bad_keeps_good():
    n, oldest, newest, _ = wa.window_span([ago(20), None, "x", ago(2)], NOW)
    ok("mixed_count", n == 2)
    ok("mixed_oldest", abs(oldest - 20.0) < 0.01)
    ok("mixed_newest", abs(newest - 2.0) < 0.01)


# --- window_span_report (the printed proof) -------------------------------
def test_report_shows_cutoff_and_span():
    r = wa.window_span_report([ago(23.5), ago(0.2)], 24, NOW, fresh_hours=6)
    ok("has_window_h", "24.0h" in r)
    ok("has_cutoff", "cutoff 2026-06-15 02:00 UTC" in r)   # now - 24h
    ok("has_count", "in-window 2" in r)
    ok("has_oldest", "oldest 23.5h" in r)
    ok("has_newest", "newest 0.2h" in r)
    ok("has_fresh", "fresh(<6h) 1" in r)


def test_report_empty_window():
    r = wa.window_span_report([], 24, NOW)
    ok("empty_count", "in-window 0" in r)
    ok("empty_no_oldest", "oldest" not in r)


def test_report_custom_label():
    r = wa.window_span_report([ago(1)], 24, NOW, label="WINDOW ['geopolitics']")
    ok("label", r.startswith("WINDOW ['geopolitics']:"))


def test_report_tolerant_of_bad_window():
    r = wa.window_span_report([ago(1)], "oops", NOW)
    ok("bad_window_defaults_24", "24.0h" in r)


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
