"""
Tests for agents/blindspot.py (NF-D2) — the pure scrape/parse/pick/format core (no network).
Card parsing, dedup, the min-sources "skip thin days" gate, max-items cap, format, splice.

    venv\\Scripts\\python.exe tests\\test_blindspot.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
import blindspot as bs  # noqa: E402

PASS = []


def ok(name, cond):
    if not cond:
        raise AssertionError(name)
    PASS.append(name)


SAMPLE = """<html><body>
<a href="/article/us-denied-israel-iran-deal_abc">Info Icon REUTERS / Jonathan Ernst/Reuters Blindspot Logo Blindspot: Only 13% Left 11 sources US denied Israel's request to view Iran deal prior to signing Left 13 % Center 12 % Right 75 %</a>
<a href="/article/melanie-cradle-ct_def">Blindspot Logo Blindspot: 0% Right 6 sources Melanie Cradle nominated as first Black woman to CT Supreme Court</a>
<a href="/article/ice-detainee_ghi">Info Icon Blindspot Logo Blindspot: Only 16% Right 39 sources ICE removed detainee protections after private outreach</a>
<a href="/about">About us Ground News</a>
<a href="/article/us-denied-israel-iran-deal_abc">Info Icon Blindspot Logo Blindspot: Only 13% Left 11 sources US denied Israel's request to view Iran deal prior to signing</a>
</body></html>"""


def test_parse_blindspots():
    items = bs.parse_blindspots(SAMPLE)
    ok("parse_count_dedup", len(items) == 3)                      # the repeated url is dropped
    first = items[0]
    ok("parse_headline", first["headline"].startswith("US denied Israel's request"))
    ok("parse_strips_breakdown", "Center" not in first["headline"] and "%" not in first["headline"])
    ok("parse_headline_full", first["headline"] == "US denied Israel's request to view Iran deal prior to signing")
    ok("parse_side", first["side"] == "Left" and first["pct"] == 13 and first["sources"] == 11)
    ok("parse_abs_url", first["url"] == "https://ground.news/article/us-denied-israel-iran-deal_abc")
    ok("parse_skips_nav", all("about" not in i["url"].lower() for i in items))
    ok("parse_no_only_word", any(i["pct"] == 0 and i["side"] == "Right" for i in items))   # "0% Right" (no 'Only')


def test_pick_min_sources_skips_thin():
    items = bs.parse_blindspots(SAMPLE)
    strong = bs.pick(items, max_items=5, min_sources=10)
    ok("pick_drops_thin", len(strong) == 2 and all(i["sources"] >= 10 for i in strong))   # drops the 6-source one
    ok("pick_max_items", len(bs.pick(items, max_items=1, min_sources=10)) == 1)
    ok("pick_page_order", bs.pick(items, 1, 10)[0]["sources"] == 11)                        # first strong, page order
    ok("pick_empty_when_all_thin", bs.pick(items, 1, 999) == [])


def test_format_blindspot():
    ok("format_empty", bs.format_blindspot([], "H") == "")
    item = [{"headline": "Big underreported story", "url": "https://ground.news/article/x",
             "side": "Left", "pct": 13, "sources": 11}]
    s = bs.format_blindspot(item, "🔦 *Blindspot of the Day*", include_link=True)
    ok("format_header", s.startswith("🔦 *Blindspot of the Day*"))
    ok("format_headline_bold", "*Big underreported story*" in s)
    ok("format_interpretation", "Under-covered by the Left" in s and "13%" in s and "11 sources" in s)
    ok("format_link", "https://ground.news/article/x" in s)
    ok("format_nolink", "https://ground.news/article/x" not in bs.format_blindspot(item, "H", include_link=False))


def test_build_end_to_end():
    block = bs.build(SAMPLE, max_items=1, min_sources=5)
    ok("build_has_pick", "US denied Israel's request" in block and "Under-covered by the Left" in block)
    ok("build_one_item", block.count("Under-covered by the") == 1)                          # max_items=1
    ok("build_empty_when_thin", bs.build(SAMPLE, 1, 999) == "")


def test_splice():
    text = "## Theme\nbody\n\n---\n_footer_"
    out = bs.splice(text, "🔦 *Blindspot of the Day*\n*x*")
    ok("splice_before_footer", "Blindspot" in out and out.index("Blindspot") < out.index("---"))
    ok("splice_keeps_footer", out.endswith("_footer_"))
    ok("splice_empty_noop", bs.splice(text, "") == text)
    ok("splice_append_no_footer", "Blindspot" in bs.splice("just text", "🔦 *Blindspot of the Day*\n*x*"))


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
