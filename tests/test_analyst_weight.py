"""
Tests for agents/analyst.weight_interpretation_text (NF-NEW14 groundwork) — the user_context.weight
scale is now generated from config, not hard-coded. The default MUST reproduce the prior prompt
text byte-for-byte (so live Telegram scoring is unchanged until the operator tunes it).

    venv\\Scripts\\python.exe tests\\test_analyst_weight.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
import analyst as a  # noqa: E402

PASS = []


def ok(name, cond):
    if not cond:
        raise AssertionError(name)
    PASS.append(name)


# The EXACT prior hard-coded text — the default output must equal this (no behaviour change).
ORIGINAL = (
    "WEIGHT INTERPRETATION: For each article, identify which interests it matches. "
    "Apply weight as a relevance adjustment after your initial scoring: "
    "+3 = significantly more relevant (push up ~2-3 points). "
    "+1 = mildly more relevant (push up ~1 point). "
    "0 = no adjustment. "
    "-1 = mildly less relevant (push down ~1 point). "
    "-3 = significantly less relevant (push down ~2-3 points). "
    "Final relevance_score must still respect the 0-10 calibration rule. "
    "Negative-weight topics should NOT be filtered out — still score them honestly, just lower."
)


def test_default_reproduces_original_byte_for_byte():
    ok("default_exact", a.weight_interpretation_text() == ORIGINAL)
    ok("explicit_defaults_exact", a.weight_interpretation_text(3, 1) == ORIGINAL)


def test_tuning_changes_the_scale():
    t = a.weight_interpretation_text(strong_points=5, mild_points=2)
    ok("strong_range", "~4-5 points" in t)
    ok("mild_points", "~2 point" in t)
    ok("changed", t != ORIGINAL)
    # the weight LABELS stay fixed (they are the user_context.weight scale, not the points)
    ok("labels_fixed", "+3 = " in t and "+1 = " in t and "-3 = " in t)


def test_strong_one_collapses_range():
    t = a.weight_interpretation_text(strong_points=1, mild_points=1)
    ok("collapsed_range", "~1 points" in t)   # lo==hi -> a single number, not a range


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
