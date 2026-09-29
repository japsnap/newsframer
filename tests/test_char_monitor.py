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


# --- strip_incomplete_tail: mid-item truncation guard (2026-09-04 Serbia-theme bug) ----

TRUNCATED_BRIEF = """## Serbia Faces New Spyware Campaign

Researchers documented a widespread spyware campaign in Serbia.

**Articles:**
[1] Serbia Faces Largest Documented Spyware Wave — https://www.technadu.com/serbia-faces-largest-documented-spyware-wave-as"""

COMPLETE_BRIEF = """## Serbia Faces New Spyware Campaign

Researchers documented a widespread spyware campaign in Serbia.

**Articles:**
[1] Serbia Faces Largest Documented Spyware Wave — [Technadu](https://www.technadu.com/serbia-faces-largest-documented-spyware-wave-as-europe-report)

---
_Briefing generated from 42 articles. 20 made the relevance cutoff. 3 themes, 5 highlights._"""


def test_truncated_bare_url_is_stripped():
    clean, stripped = cm.strip_incomplete_tail(TRUNCATED_BRIEF)
    ok("trunc_stripped_something", stripped > 0)
    ok("trunc_dangling_url_gone", "technadu.com/serbia-faces-largest-documented-spyware-wave-as" not in clean)
    ok("trunc_flag_fires", cm.truncation_flag(stripped) is not None)
    ok("trunc_flag_has_marker", cm.TRUNCATION_MARKER in cm.truncation_flag(stripped))


def test_complete_brief_is_untouched():
    # Negative test: a well-formed, complete brief must NOT lose any content.
    clean, stripped = cm.strip_incomplete_tail(COMPLETE_BRIEF)
    ok("complete_nothing_stripped", stripped == 0)
    ok("complete_text_unchanged", clean == COMPLETE_BRIEF)
    ok("complete_no_flag", cm.truncation_flag(stripped) is None)


def test_strip_never_eats_more_than_max_strip_lines():
    junk = "\n".join(f"line {i} with no ending" for i in range(20))
    clean, stripped = cm.strip_incomplete_tail(junk, max_strip=5)
    ok("bounded_stripped", stripped == 5)
    ok("bounded_kept_some", clean.count("\n") >= 10)


def test_strip_drops_trailing_blank_lines_first():
    text = COMPLETE_BRIEF + "\n\n\n"
    clean, stripped = cm.strip_incomplete_tail(text)
    ok("blank_trailing_no_falsepositive", stripped == 0)
    ok("blank_trailing_trimmed", clean == COMPLETE_BRIEF)


def test_japanese_and_urdu_endings_are_complete():
    # A ja or ur brief ends on its own full stop; the guard must not trim it.
    ja = "## 日本の動向\n日銀は政策金利を据え置いた。"
    ur = "## پاکستان\nحکومت نے پٹرول کی قیمت بڑھا دی۔"
    ok("ja_full_stop_untouched", cm.strip_incomplete_tail(ja) == (ja, 0))
    ok("ur_full_stop_untouched", cm.strip_incomplete_tail(ur) == (ur, 0))
    # Negative: a Japanese line cut mid-link is still trimmed.
    cut = ja + "\n[1] [記事](https://example.jp/news/abc"
    clean, n = cm.strip_incomplete_tail(cut)
    ok("ja_cut_link_trimmed", n == 1 and clean == ja)


def test_strip_tolerant_of_junk_input():
    ok("strip_none", cm.strip_incomplete_tail(None) == (None, 0))
    ok("strip_empty", cm.strip_incomplete_tail("") == ("", 0))
    ok("truncation_flag_bad_input_none", cm.truncation_flag("not-a-number") is None)
    ok("truncation_flag_zero_none", cm.truncation_flag(0) is None)


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
