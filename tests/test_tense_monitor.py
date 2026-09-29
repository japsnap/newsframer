"""
Tests for agents/tense_monitor.py — highlight tense/certainty guard (2026-09-05 bug: a
highlight said Anthropic "completed a $2 trillion IPO" when the source said it "could
seek" that valuation in a PLANNED October offering). Pure keyword logic. No DB, no LLM.

    venv\\Scripts\\python.exe tests\\test_tense_monitor.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
import tense_monitor as tm  # noqa: E402

PASS = []


def ok(name, cond):
    if not cond:
        raise AssertionError(name)
    PASS.append(name)


def _highlight(title, url, differentiator="", reasoning="", content_raw=""):
    return {
        "title": title,
        "url": url,
        "content_raw": content_raw,
        "score": {"differentiator": differentiator, "reasoning": reasoning},
    }


# --- the reported bug shape: hedged source -> a bullet that states it as done ----------

def test_anthropic_ipo_bug_is_caught():
    h = _highlight(
        "Anthropic Weighs $2 Trillion Valuation",
        "https://example.com/anthropic-ipo",
        reasoning="Anthropic could seek a $2 trillion valuation in a planned October IPO.",
    )
    brief = ("## Highlights\n"
             "- **Anthropic Completed a $2 Trillion IPO** — Anthropic completed its IPO at "
             "a $2 trillion valuation. [Reuters](https://example.com/anthropic-ipo)\n")
    mismatches = tm.find_tense_mismatches([h], brief)
    ok("bug_shape_caught", len(mismatches) == 1)
    ok("bug_shape_url", mismatches[0]["url"] == "https://example.com/anthropic-ipo")
    flag = tm.tense_mismatch_flag([h], brief)
    ok("bug_shape_flag_fires", flag is not None and tm.TENSE_MISMATCH_MARKER in flag)


# --- tense correctly preserved -> no flag (negative test) ------------------------------

def test_hedge_preserved_no_flag():
    h = _highlight(
        "Anthropic Weighs $2 Trillion Valuation",
        "https://example.com/anthropic-ipo",
        reasoning="Anthropic could seek a $2 trillion valuation in a planned October IPO.",
    )
    brief = ("## Highlights\n"
             "- **Anthropic Could Seek $2 Trillion IPO Valuation** — Anthropic could seek "
             "this valuation in a planned October offering. [Reuters](https://example.com/anthropic-ipo)\n")
    ok("hedge_preserved_clean", tm.find_tense_mismatches([h], brief) == [])
    ok("hedge_preserved_no_flag", tm.tense_mismatch_flag([h], brief) is None)


# --- source ALREADY a done deal -> "completed" language is correct, not a mismatch -----

def test_already_completed_source_no_false_positive():
    h = _highlight(
        "Company X Closes Series B",
        "https://example.com/company-x",
        reasoning="Company X closed its $50 million Series B round on Tuesday.",
    )
    brief = ("## Highlights\n"
             "- **Company X Completed Its Series B** — Company X completed a $50 million "
             "round. [TechCrunch](https://example.com/company-x)\n")
    ok("already_done_clean", tm.find_tense_mismatches([h], brief) == [])


# --- only the highlight whose URL is present is checked ---------------------------------

def test_only_matching_url_is_compared():
    hedged = _highlight("Hedged Story", "https://example.com/hedged",
                        reasoning="The company could seek new funding soon.")
    unrelated = _highlight("Unrelated Story", "https://example.com/unrelated",
                           reasoning="Nothing hedged here at all.")
    # brief only renders the UNRELATED highlight; the hedged one never made the cut.
    brief = "## Highlights\n- **Unrelated Story** — completed and confirmed. [Src](https://example.com/unrelated)\n"
    ok("no_url_no_compare", tm.find_tense_mismatches([hedged, unrelated], brief) == [])


# --- tolerant of junk / missing fields ---------------------------------------------------

def test_tolerant_of_missing_fields():
    ok("none_highlights", tm.find_tense_mismatches(None, "some text") == [])
    ok("empty_highlights", tm.find_tense_mismatches([], "some text") == [])
    ok("none_brief", tm.find_tense_mismatches([_highlight("T", "https://e.com/x")], None) == [])
    bare = [{"title": "No score key", "url": "https://e.com/y"}]
    ok("missing_score_key", tm.find_tense_mismatches(bare, "- **T** — x [S](https://e.com/y)") == [])


def test_hedge_and_done_deal_word_detection():
    ok("hedge_could", tm.source_is_hedged("It could raise more funding."))
    ok("hedge_planned", tm.source_is_hedged("A planned IPO for October."))
    ok("hedge_none", tm.source_is_hedged("It raised $5 million on Tuesday.") is False)
    ok("done_completed", tm.bullet_is_done_deal("Completed the acquisition."))
    ok("done_none", tm.bullet_is_done_deal("Could complete the acquisition soon.") is False)


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
