"""
Tests for agents/critic.py — the pre-send Critic (spec §10.13 / NF-F1).
Deterministic structural checks; reports by severity, never patches. No DB, no LLM.

    venv\\Scripts\\python.exe tests\\test_critic.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
import critic as c  # noqa: E402

PASS = []


def ok(name, cond):
    if not cond:
        raise AssertionError(name)
    PASS.append(name)


GOOD = """# NewsFramer Briefing — 2026-06-14

## First Theme Title
Body about the first theme.

**Articles:**
[1] [Headline one](https://example.com/a) — Source A

## Second Theme Title
Body about the second theme.

**Articles:**
[1] [Headline two](https://example.com/b) — Source B

## Third Theme Title
Body about the third theme.

**Articles:**
[1] [Headline three](https://example.com/c) — Source C

## Highlights
- Something happened [link](https://example.com/d)
"""


def codes(findings):
    return {f["code"] for f in findings}


def test_clean_brief_has_no_findings():
    # Negative test: a well-formed brief must NOT trip any check (no false positives).
    f = c.critique(GOOD, max_chars=5000)
    ok("clean_none", f == [])
    ok("clean_worst_none", c.worst_severity(f) is None)
    ok("clean_report", "no issues" in c.format_report(f))


def test_empty_brief_is_critical():
    f = c.critique("   ", max_chars=5000)
    ok("empty_code", "empty_brief" in codes(f))
    ok("empty_worst", c.worst_severity(f) == c.CRITICAL)


def test_no_citations_anywhere_is_critical():
    f = c.critique("# Brief\n\n## A Theme\nBody with no link at all.\n", max_chars=5000)
    ok("no_cite_critical", "no_citations" in codes(f))


def test_single_theme_without_citation_flagged():
    txt = GOOD.replace("[1] [Headline two](https://example.com/b) — Source B", "no link here")
    f = c.critique(txt, max_chars=5000)
    ok("theme_no_cite", "theme_no_citation" in codes(f))
    ok("theme_no_cite_important",
       any(x["code"] == "theme_no_citation" and x["severity"] == c.IMPORTANT for x in f))


def test_empty_section_flagged():
    f = c.critique("# Brief\n\n## Empty One\n## Real Theme\nBody [x](https://e.com/x)\n", max_chars=5000)
    ok("empty_section", "empty_section" in codes(f))


def test_char_overrun_flagged():
    f = c.critique(GOOD, max_chars=50)  # tiny cap forces an overrun
    ok("overrun", "char_overrun" in codes(f))


def test_few_themes_is_minor():
    f = c.critique("# Brief\n\n## Only Theme\nBody [x](https://e.com/x)\n", max_chars=5000)
    ok("few_themes", "few_themes" in codes(f))
    ok("few_themes_minor",
       any(x["code"] == "few_themes" and x["severity"] == c.MINOR for x in f))


def test_critic_never_mutates_input():
    # "Never patches": critique RETURNS findings; the brief text must be untouched.
    before = GOOD
    _ = c.critique(GOOD, max_chars=50)
    ok("input_unchanged", GOOD == before)


def test_format_report_groups_by_severity():
    f = c.critique("   ", max_chars=5000)
    ok("report_critical_header", "Critical" in c.format_report(f))


def test_theme_count_excludes_highlights_and_investigations():
    ok("theme_count_three", c.theme_count(GOOD) == 3)
    ok("theme_count_empty", c.theme_count("") == 0)


def test_at_or_above_threshold():
    # the alert gate: only ping when a finding is at/above the configured severity
    crit = [{"severity": c.CRITICAL, "code": "x", "message": "m"}]
    imp = [{"severity": c.IMPORTANT, "code": "y", "message": "m"}]
    minor = [{"severity": c.MINOR, "code": "z", "message": "m"}]
    ok("at_crit_meets_important", c.at_or_above(crit, c.IMPORTANT) is True)
    ok("at_important_meets_important", c.at_or_above(imp, c.IMPORTANT) is True)
    ok("at_minor_below_important", c.at_or_above(minor, c.IMPORTANT) is False)
    ok("at_minor_meets_minor", c.at_or_above(minor, c.MINOR) is True)
    ok("at_empty_false", c.at_or_above([], c.IMPORTANT) is False)
    ok("at_unknown_severity_defaults_important", c.at_or_above(minor, "Bogus") is False)


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
