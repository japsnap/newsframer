"""
Tests for agents/link_monitor.py (NF-NEW1) — bare-URL detection. No DB, no LLM.

The Telegram brief must cite a clickable SOURCE NAME (`[Source](url)`), never a raw URL.
This pins the deterministic safety-net that catches a regression where the Writer slips a
bare `https://...` into the output. Log-only — never alters or blocks the brief.

    venv\\Scripts\\python.exe tests\\test_link_monitor.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
import link_monitor as lm  # noqa: E402

PASS = []


def ok(name, cond):
    if not cond:
        raise AssertionError(name)
    PASS.append(name)


# --- the clean, NF-NEW1-compliant shapes produce NO flag ------------------
def test_markdown_link_is_not_bare():
    ok("theme_cite_clean",
       lm.bare_url_flag("[1] Bitcoin Slides — [TRT Global](https://trt.example/x)") is None)
    ok("highlight_cite_clean",
       lm.bare_url_flag("- **Title** — summary. [Reuters](http://r.example/a)") is None)
    ok("no_url_at_all", lm.bare_url_flag("No links here, just prose about US and AI.") is None)
    ok("multi_clean",
       lm.bare_url_flag("[A](https://a.example) and [B](https://b.example)") is None)


# --- a bare URL IS flagged -------------------------------------------------
def test_bare_url_flagged():
    w = lm.bare_url_flag("See https://example.com/story for more.")
    ok("bare_flagged", w is not None and lm.BARE_URL_MARKER in w)
    ok("bare_count_one", w is not None and "1 raw URL" in w)
    ok("bare_token_shown", w is not None and "https://example.com/story" in w)


def test_mixed_bare_and_linked():
    # one proper link + one bare URL -> flags only the bare one
    text = "[Reuters](https://r.example/a) but also raw https://leak.example/b here"
    w = lm.bare_url_flag(text)
    ok("mixed_flagged", w is not None and "1 raw URL" in w)
    ok("mixed_only_bare_token", w is not None and "https://leak.example/b" in w and "r.example" not in w)


def test_counts_multiple_and_truncates_list():
    text = "a http://1.example b http://2.example c http://3.example d http://4.example"
    w = lm.bare_url_flag(text)
    ok("count_four", w is not None and "4 raw URL" in w)
    ok("shows_three_plus_more", w is not None and "+1 more" in w)


def test_token_stops_at_delimiters():
    urls = lm.find_bare_urls("(https://x.example/p) trailing")
    ok("stops_at_paren", urls == ["https://x.example/p"])
    urls2 = lm.find_bare_urls("https://y.example/p\nnext line")
    ok("stops_at_newline", urls2 == ["https://y.example/p"])


def test_url_at_start_of_string_is_bare():
    ok("start_bare", lm.find_bare_urls("https://z.example") == ["https://z.example"])


def test_case_insensitive_scheme():
    ok("https_caps", lm.bare_url_flag("HTTPS://CAPS.example/x") is not None)


# --- tolerant of junk ------------------------------------------------------
def test_tolerant():
    ok("none_input", lm.bare_url_flag(None) is None)
    ok("empty_str", lm.bare_url_flag("") is None)
    ok("int_input", lm.bare_url_flag(12345) is None)
    ok("find_none", lm.find_bare_urls(None) == [])


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
