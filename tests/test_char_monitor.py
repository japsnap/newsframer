"""
Tests for agents/char_monitor.py — briefing char-overrun flag (NF-F2, spec §15).

Pure logic: given a brief length, the theme-scaled cap, and a tolerance ratio,
return a greppable flag string when over cap (beyond tolerance), else None. No I/O.

    venv\\Scripts\\python.exe tests\\test_char_monitor.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
import char_monitor as cm  # noqa: E402

PASS = []


def ok(name, cond):
    if not cond:
        raise AssertionError(name)
    PASS.append(name)


# --- the flag fires when over cap ------------------------------------------
def test_over_cap_flags():
    flag = cm.overrun_flag(9000, 8000, 1.0)
    ok("over_returns_str", isinstance(flag, str))
    ok("over_has_marker", cm.OVERRUN_MARKER in flag)
    ok("over_reports_len", "9000" in flag)
    ok("over_reports_cap", "8000" in flag)
    ok("over_reports_delta", "+1000" in flag)


def test_over_cap_percent_is_vs_cap():
    # 1000 over an 8000 cap = 12.5%, measured against the cap (not the threshold).
    ok("pct_vs_cap", "12.5%" in cm.overrun_flag(9000, 8000, 1.0))


# --- the flag stays silent within cap / tolerance --------------------------
def test_under_cap_silent():
    ok("under_none", cm.overrun_flag(7000, 8000, 1.0) is None)


def test_exactly_at_cap_silent():
    ok("equal_none", cm.overrun_flag(8000, 8000, 1.0) is None)


def test_tolerance_suppresses_small_overrun():
    # 8800 is 10% over an 8000 cap; a 1.15 (15%) tolerance must suppress it...
    ok("tol_suppresses", cm.overrun_flag(8800, 8000, 1.15) is None)
    # ...but a 1.0 tolerance (default) still flags it.
    ok("tol_default_flags", cm.overrun_flag(8800, 8000, 1.0) is not None)


def test_tolerance_still_flags_beyond_it():
    # 9500 is ~18.75% over; beyond a 15% tolerance -> flags, delta still vs cap.
    flag = cm.overrun_flag(9500, 8000, 1.15)
    ok("beyond_tol_flags", flag is not None)
    ok("beyond_tol_delta_vs_cap", "+1500" in flag)


# --- a monitor must never crash the brief ----------------------------------
def test_bad_inputs_return_none():
    ok("zero_cap_none", cm.overrun_flag(9000, 0, 1.0) is None)
    ok("neg_cap_none", cm.overrun_flag(9000, -5, 1.0) is None)
    ok("none_cap_none", cm.overrun_flag(9000, None, 1.0) is None)
    ok("none_len_none", cm.overrun_flag(None, 8000, 1.0) is None)
    ok("str_garbage_none", cm.overrun_flag("lots", "many", 1.0) is None)


def test_numeric_strings_coerced():
    # config / json sometimes hand numbers through as strings — coerce, don't choke.
    ok("numeric_str_flags", cm.overrun_flag("9000", "8000", "1.0") is not None)


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
