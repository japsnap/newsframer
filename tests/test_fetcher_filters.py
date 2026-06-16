"""
Tests for the fetcher's PURE gate logic — the filters that silently decide what gets
fetched: junk-URL filter, §8.7 scrape-day calendar, §8.1 per-source window, PR filter,
scrape-vs-RSS routing, and intra-batch URL dedup. No network, no DB (these are pure).

    venv\\Scripts\\python.exe tests\\test_fetcher_filters.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
import fetcher as f  # noqa: E402

PASS = []


def ok(name, cond):
    if not cond:
        raise AssertionError(name)
    PASS.append(name)


# --- source_window_hours (§8.1) -------------------------------------------
CFG = {"fetch_hours_back": 24, "first_run_hours_back": 48}


def test_source_window_default():
    ok("default_24", f.source_window_hours(CFG, {}, False) == 24)
    ok("per_source", f.source_window_hours(CFG, {"fetch_window_hours": 72}, False) == 72)


def test_source_window_first_run_floor():
    # First run never drops below first_run_hours_back, even if the source asks for less.
    ok("first_run_floor", f.source_window_hours(CFG, {"fetch_window_hours": 12}, True) == 48)
    ok("first_run_keeps_larger", f.source_window_hours(CFG, {"fetch_window_hours": 168}, True) == 168)
    ok("first_run_no_source", f.source_window_hours(CFG, {}, True) == 48)


# --- is_scrape_source (RSS vs scrape routing) -----------------------------
def test_is_scrape_source():
    ok("rss_is_not_scrape", f.is_scrape_source({"has_rss": True, "rss_url": "http://x/feed"}) is False)
    ok("no_rss_is_scrape", f.is_scrape_source({"has_rss": False, "rss_url": None}) is True)
    ok("rss_flag_but_no_url", f.is_scrape_source({"has_rss": True, "rss_url": None}) is True)
    ok("empty", f.is_scrape_source({}) is True)


# --- scrape_scheduled_today (§8.7 weekly calendar) ------------------------
def test_scrape_calendar():
    ok("null_runs_any_day", f.scrape_scheduled_today({}, "mon") is True)
    ok("empty_runs_any_day", f.scrape_scheduled_today({"scrape_days": ""}, "mon") is True)
    ok("match", f.scrape_scheduled_today({"scrape_days": "wed,sat"}, "wed") is True)
    ok("no_match", f.scrape_scheduled_today({"scrape_days": "wed,sat"}, "mon") is False)
    ok("full_name_trimmed", f.scrape_scheduled_today({"scrape_days": "Wednesday, Saturday"}, "sat") is True)
    ok("spaces_ok", f.scrape_scheduled_today({"scrape_days": " tue , thu "}, "thu") is True)


# --- is_pr_article (PR filter, gated by source notes) ---------------------
def test_pr_filter():
    pr_src = {"notes": "Avoid PR articles from this wire"}
    ok("pr_caught", f.is_pr_article("Sponsored: new token launch", pr_src) is True)
    ok("pr_press_release", f.is_pr_article("PRESS RELEASE: Acme partners with X", pr_src) is True)
    ok("clean_kept", f.is_pr_article("Bitcoin falls 5% on macro fears", pr_src) is False)
    ok("no_notes_never_pr", f.is_pr_article("Sponsored content", {}) is False)


# --- is_junk_url -----------------------------------------------------------
GOOD_URL = "https://example.com/2026/06/some-real-news-article-headline"
GOOD_TITLE = "A genuine news headline about something"


def test_junk_basic_guards():
    ok("good_kept", f.is_junk_url(GOOD_URL, GOOD_TITLE) is False)
    ok("empty_url", f.is_junk_url("", GOOD_TITLE) is True)
    ok("empty_title", f.is_junk_url(GOOD_URL, "") is True)
    ok("short_url", f.is_junk_url("http://x.co/a", GOOD_TITLE) is True)        # < 30 chars
    ok("short_title", f.is_junk_url(GOOD_URL, "too short") is True)            # < 15 chars
    ok("not_http", f.is_junk_url("ftp://example.com/very/long/path/here/ok", GOOD_TITLE) is True)


def test_junk_patterns():
    pats = [
        {"pattern": "/tag/", "pattern_type": "url_contains"},
        {"pattern": ".pdf", "pattern_type": "url_endswith"},
        {"pattern": "live blog", "pattern_type": "title_contains"},
    ]
    ok("url_contains", f.is_junk_url("https://example.com/tag/crypto-roundup-page", GOOD_TITLE, pats) is True)
    ok("url_endswith", f.is_junk_url("https://example.com/reports/the-annual-summary.pdf", GOOD_TITLE, pats) is True)
    ok("title_contains", f.is_junk_url(GOOD_URL, "Ukraine war LIVE BLOG updates today", pats) is True)
    ok("no_pattern_match", f.is_junk_url(GOOD_URL, GOOD_TITLE, pats) is False)


# --- deduplicate_batch (intra-run URL dedup) ------------------------------
def test_deduplicate_batch():
    arts = [{"url": "a", "title": "1"}, {"url": "b", "title": "2"},
            {"url": "a", "title": "1 dup"}, {"url": "c", "title": "3"}]
    out = f.deduplicate_batch(arts)
    ok("deduped_len", len(out) == 3)
    ok("keeps_first", [x["url"] for x in out] == ["a", "b", "c"])


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
