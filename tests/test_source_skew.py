"""
Tests for agents/source_skew.py (NF-D3) — pure source-skew detection. No DB, no LLM.

    venv\\Scripts\\python.exe tests\\test_source_skew.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
import source_skew as ss  # noqa: E402

PASS = []


def ok(name, cond):
    if not cond:
        raise AssertionError(name)
    PASS.append(name)


def test_norm():
    ok("left", ss._norm("Left") == "left")
    ok("lean_left", ss._norm("Lean Left") == "left")
    ok("right", ss._norm("Lean Right") == "right")
    ok("center", ss._norm("Center") == "center")
    ok("middle", ss._norm("Middle") == "center")
    ok("none", ss._norm(None) is None and ss._norm("") is None)
    ok("unknown", ss._norm("mixed") is None)


def test_warns_when_skewed_left():
    w = ss.skew_warning([("a", "Left"), ("b", "Lean Left"), ("c", "Left")])
    ok("left_warn", w is not None and "Left" in w and "no Right" in w)


def test_warns_when_skewed_right():
    w = ss.skew_warning([("a", "Right"), ("b", "Lean Right"), ("c", "Right")])
    ok("right_warn", w is not None and "Right" in w and "no Left" in w)


def test_balanced_both_sides_present():
    ok("both_sides", ss.skew_warning([("a", "Left"), ("b", "Left"), ("c", "Right")]) is None)


def test_center_dilutes_skew():
    # 3 left + 2 center = 5 placed; left 3/5 = 60% < 75% -> NOT skewed (centrists balance).
    ok("center_dilutes",
       ss.skew_warning([("a", "Left"), ("b", "Left"), ("c", "Left"), ("d", "Center"), ("e", "Center")]) is None)
    # 3 left + 1 center = 4 placed; left 3/4 = 75%, no right -> skewed.
    ok("center_one_still_skewed",
       ss.skew_warning([("a", "Left"), ("b", "Left"), ("c", "Left"), ("d", "Center")]) is not None)


def test_needs_min_sources():
    ok("too_few", ss.skew_warning([("a", "Left"), ("b", "Left")]) is None)   # only 2 placed


def test_dedup_by_source():
    # 5 articles but only 2 DISTINCT sources -> < 3 -> no warning.
    items = [("a", "Left"), ("a", "Left"), ("a", "Left"), ("b", "Left"), ("b", "Left")]
    ok("dedup", ss.skew_warning(items) is None)


def test_unknown_bias_dropped_from_count():
    # 3 known-left + 2 unknown -> placed = 3 left -> skewed (unknowns don't count).
    w = ss.skew_warning([("a", "Left"), ("b", "Left"), ("c", "Lean Left"), ("d", None), ("e", "weird")])
    ok("unknown_dropped", w is not None and "3/3" in w)


def test_tolerant_of_malformed():
    ok("empty", ss.skew_warning([]) is None)
    ok("none_arg", ss.skew_warning(None) is None)
    ok("bad_items", ss.skew_warning([("a", "Left"), None, "x", ("b",), ("c", "Left"), ("d", "Left")]) is not None)


# --- coverage_note (user-facing 'left/right media only') ------------------
def test_coverage_note():
    ok("all_left", ss.coverage_note([("a", "left"), ("b", "left")]) == "left")
    ok("all_right", ss.coverage_note([("a", "right"), ("b", "right")]) == "right")
    ok("single_left", ss.coverage_note([("a", "left")]) == "left")
    ok("left_plus_center_is_none", ss.coverage_note([("a", "left"), ("b", "center")]) is None)
    ok("both_sides_none", ss.coverage_note([("a", "left"), ("b", "right")]) is None)
    ok("only_center_none", ss.coverage_note([("a", "center"), ("b", "center")]) is None)
    ok("dedup_one_source", ss.coverage_note([("a", "left"), ("a", "left"), ("a", "left")]) == "left")
    ok("unknown_ignored", ss.coverage_note([("a", "left"), ("b", None), ("c", "weird")]) == "left")
    ok("empty_none", ss.coverage_note([]) is None and ss.coverage_note(None) is None)


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
