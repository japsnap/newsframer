"""
Tests for agents/drop_reports.py — the PURE logic of the drop-report feature
(spec 8.5, basic version): slug generation, weave-or-standalone detection,
deterministic Investigations rendering, and splicing it into the brief.

No DB, no LLM. Runnable directly:
    venv\\Scripts\\python.exe tests\\test_drop_reports.py
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
import drop_reports as dr  # noqa: E402

PASS = []


def ok(name, cond):
    if not cond:
        raise AssertionError(name)
    PASS.append(name)


SLUG_RE = re.compile(r"^[a-z0-9-]+$")


# --- pick_diverse (NF-NEW3: no single source monopolises Investigations) ---
def _items(*srcs):
    return [{"id": i, "src": s} for i, s in enumerate(srcs)]


def _src(it):
    return it["src"]


def test_pick_diverse_caps_one_per_source():
    ordered = _items("mee", "mee", "mee", "intercept", "technadu")  # best-first
    got = dr.pick_diverse(ordered, 3, 1, _src)
    ok("pd_three", len(got) == 3)
    ok("pd_distinct_sources", len({_src(x) for x in got}) == 3)
    ok("pd_keeps_top_item", got[0]["src"] == "mee")
    ok("pd_order", [x["src"] for x in got] == ["mee", "intercept", "technadu"])


def test_pick_diverse_backfills_when_too_few_sources():
    # only one source -> can't diversify; backfill keeps the top items (old behaviour).
    got = dr.pick_diverse(_items("mee", "mee", "mee", "mee"), 3, 1, _src)
    ok("pd_backfill_len", len(got) == 3)
    ok("pd_backfill_all_mee", all(x["src"] == "mee" for x in got))


def test_pick_diverse_max_per_source_two():
    got = dr.pick_diverse(_items("a", "a", "a", "b"), 3, 2, _src)
    ok("pd_two_per", [x["src"] for x in got] == ["a", "a", "b"])


def test_pick_diverse_empty_and_order():
    ok("pd_empty", dr.pick_diverse([], 3, 1, _src) == [])
    got = dr.pick_diverse(_items("a", "b", "c", "d"), 2, 1, _src)
    ok("pd_top_two", [x["src"] for x in got] == ["a", "b"])


# --- make_slug -------------------------------------------------------------
def test_slug_basic():
    s = dr.make_slug("Pegasus traced to new operator")
    ok("slug_basic_charset", bool(SLUG_RE.match(s)))
    ok("slug_basic_prefix", s.startswith("pegasus"))


def test_slug_strips_punctuation_and_unicode():
    s = dr.make_slug("NSO's spyware: who's next? — café")
    ok("slug_clean", bool(SLUG_RE.match(s)) and "'" not in s and ":" not in s)


def test_slug_collision_suffixes():
    s1 = dr.make_slug("Pegasus traced to new operator")
    s2 = dr.make_slug("Pegasus traced to new operator", existing={s1})
    ok("slug_collision_differs", s1 != s2)
    ok("slug_collision_valid", bool(SLUG_RE.match(s2)))


def test_slug_garbage_fallback():
    s = dr.make_slug("!!! ??? ---")
    ok("slug_garbage_nonempty", len(s) > 0 and bool(SLUG_RE.match(s)))


def test_slug_capped_length():
    s = dr.make_slug("a very long investigative headline that just keeps going and going forever")
    ok("slug_capped", len(s) <= 40)


# --- is_woven --------------------------------------------------------------
def test_woven_shared_topic():
    ok("woven_true", dr.is_woven(["spyware", "pegasus"], ["pegasus", "surveillance"]) is True)


def test_woven_no_overlap():
    ok("woven_false", dr.is_woven(["spyware"], ["bitcoin", "etf"]) is False)


def test_woven_empty_drop():
    ok("woven_empty_drop", dr.is_woven([], ["pegasus"]) is False)


def test_woven_empty_main():
    ok("woven_empty_main", dr.is_woven(["pegasus"], []) is False)


# --- render_investigations_section -----------------------------------------
def _drop(title="Pegasus traced to new operator", slug="pegasus", source="Citizen Lab",
          url="https://citizenlab.ca/x", short="Citizen Lab links the spyware to a new operator."):
    return {"title": title, "slug": slug, "source": source, "url": url, "short": short}


def test_render_empty():
    ok("render_empty", dr.render_investigations_section([]) == "")


def test_render_one_drop_structure():
    md = dr.render_investigations_section([_drop()])
    ok("render_header", "## 🔍 Investigations" in md)
    ok("render_marker", "🔍 **Pegasus traced to new operator**" in md)
    ok("render_short", "links the spyware" in md)
    ok("render_source_link", "[Citizen Lab](https://citizenlab.ca/x)" in md)
    ok("render_more_hint", 'more: pegasus' in md)


def test_render_two_drops():
    md = dr.render_investigations_section([_drop(), _drop(title="Second", slug="second")])
    ok("render_two", md.count("🔍 **") == 2)


# --- splice_investigations -------------------------------------------------
SECTION = "## 🔍 Investigations\n\n🔍 **X** — y. [S](u)\n_Investigation · reply \"more: x\"._"


def test_splice_before_highlights():
    brief = "# Brief\n\n## Theme\nbody\n\n## Highlights\n- a\n\n---\n_footer_"
    out = dr.splice_investigations(brief, SECTION)
    ok("splice_before_highlights", out.index("Investigations") < out.index("## Highlights"))
    ok("splice_keeps_highlights", "## Highlights" in out)


def test_splice_before_footer_when_no_highlights():
    brief = "# Brief\n\n## Theme\nbody\n\n---\n_footer_"
    out = dr.splice_investigations(brief, SECTION)
    ok("splice_before_footer", out.index("Investigations") < out.index("---\n_footer_"))


def test_splice_append_when_neither():
    brief = "# Brief\n\n## Theme\nbody"
    out = dr.splice_investigations(brief, SECTION)
    ok("splice_append", out.rstrip().endswith('reply "more: x"._'))


def test_splice_empty_section_unchanged():
    brief = "# Brief\n\n## Highlights\n- a"
    ok("splice_empty_noop", dr.splice_investigations(brief, "") == brief)


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
