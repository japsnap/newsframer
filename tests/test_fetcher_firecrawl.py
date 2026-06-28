"""
Tests for the NF-B4 Firecrawl scrape path (spec §3.3) in agents/fetcher.py.
Pure + mocked — no real network. Covers:
  - markdown link parsing (title from [title](url); drops short titles, dups, images)
  - the request shape sent to Firecrawl matches the v2 contract
  - every failure mode (no key, empty url, success=false, no markdown, non-JSON) returns None
  - fetch_web: OFF leaves the BeautifulSoup path untouched (Firecrawl never called);
    ON+fail falls back to BeautifulSoup; ON+success builds articles.

    venv\\Scripts\\python.exe tests\\test_fetcher_firecrawl.py
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


# --- fakes ------------------------------------------------------------------
class FakeResp:
    def __init__(self, payload=None, text=""):
        self._payload = payload
        self.text = text

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def fake_post(payload, capture=None):
    def _post(url, headers=None, json=None, timeout=None):
        if capture is not None:
            capture["url"], capture["headers"], capture["json"] = url, headers, json
        return FakeResp(payload)
    return _post


# EXACT v2 shape: {"success": true, "data": {"markdown": ..., "links": [...]}}
GOOD_MD = (
    "# Latest\n"
    "[Israel and Iran agree ceasefire after twelve day war](https://trt.example/a-real-long-headline)\n"
    "[Markets rally as oil prices ease on truce news](https://trt.example/another-long-headline)\n"
    "[Home](https://trt.example/)\n"                       # title too short -> dropped
    "[Israel and Iran agree ceasefire after twelve day war](https://trt.example/a-real-long-headline)\n"  # dup url -> dropped
    "![A long descriptive alt text for a banner image](https://trt.example/img.png)\n"  # image -> dropped
)
GOOD_PAYLOAD = {"success": True, "data": {"markdown": GOOD_MD, "links": ["https://trt.example/a-real-long-headline"]}}

HTML_LISTING = (
    "<html><body>"
    '<a href="https://bs.example/a-genuine-long-article-headline">A genuine long article headline here</a>'
    '<a href="https://bs.example/x">short</a>'
    "</body></html>"
)


def _html_resp():
    return FakeResp(text=HTML_LISTING)


def _with_key(fn):
    """Run fn() with FIRECRAWL_API_KEY present, restoring env after."""
    prev = os.environ.get("FIRECRAWL_API_KEY")
    os.environ["FIRECRAWL_API_KEY"] = "fc-test-key"
    try:
        return fn()
    finally:
        if prev is None:
            os.environ.pop("FIRECRAWL_API_KEY", None)
        else:
            os.environ["FIRECRAWL_API_KEY"] = prev


# --- firecrawl_list_links: parsing + request shape --------------------------
def test_parse_markdown_links():
    cap = {}
    orig = f.requests.post
    f.requests.post = fake_post(GOOD_PAYLOAD, cap)
    try:
        links = _with_key(lambda: f.firecrawl_list_links("https://trt.example/news"))
    finally:
        f.requests.post = orig
    ok("returns_list", isinstance(links, list))
    urls = [l["url"] for l in links]
    ok("kept_two_real", urls == ["https://trt.example/a-real-long-headline",
                                  "https://trt.example/another-long-headline"])
    ok("dropped_short_title", "https://trt.example/" not in urls)
    ok("dropped_dup", urls.count("https://trt.example/a-real-long-headline") == 1)
    ok("dropped_image", "https://trt.example/img.png" not in urls)
    ok("title_carried", links[0]["title"].startswith("Israel and Iran"))
    # request shape sent to Firecrawl matches the v2 contract
    ok("posted_to_api_url", cap["url"] == f.FIRECRAWL_API_URL)
    ok("posted_target_url", cap["json"]["url"] == "https://trt.example/news")
    ok("posted_formats", cap["json"]["formats"] == ["markdown", "links"])
    ok("auth_bearer", cap["headers"]["Authorization"].startswith("Bearer "))


def test_drops_nested_image_links_and_cleans_titles():
    # Mirrors the REAL TRT World markdown the live dry-run exposed: a clean text link whose label
    # spans lines with `\` hard-breaks + a summary, plus a nested [![alt](img)](article) whose first
    # match captures the CloudFront IMAGE url. We must keep the article url with a flattened title
    # and never emit the image url.
    md = (
        "[Rubio reassures Gulf allies on Iran deal during UAE visit\\\n\\\n"
        "Washington moves to calm the region](https://trtworld.com/article/29ff97a2a6ed)\n"
        "[![Peace will prevail in region: Turkish president](https://cdn.example/img/abc.jpg)]"
        "(https://trtworld.com/article/7810ec883a99)\n"
    )
    orig = f.requests.post
    f.requests.post = fake_post({"success": True, "data": {"markdown": md}})
    try:
        links = _with_key(lambda: f.firecrawl_list_links("https://www.trtworld.com/"))
    finally:
        f.requests.post = orig
    urls = [l["url"] for l in links]
    ok("kept_article_urls_only", urls == ["https://trtworld.com/article/29ff97a2a6ed",
                                           "https://trtworld.com/article/7810ec883a99"])
    ok("no_image_url", not any("cdn.example" in u for u in urls))
    ok("title_flattened_no_backslash", "\\" not in links[0]["title"] and "\n" not in links[0]["title"])
    ok("title_collapsed_spaces", "  " not in links[0]["title"])
    ok("title_starts_headline", links[0]["title"].startswith("Rubio reassures Gulf allies"))


def test_max_links_cap():
    md = "\n".join(f"[A sufficiently long article headline number {i}](https://x/article-{i})" for i in range(10))
    orig = f.requests.post
    f.requests.post = fake_post({"success": True, "data": {"markdown": md}})
    try:
        links = _with_key(lambda: f.firecrawl_list_links("https://x/news", max_links=3))
    finally:
        f.requests.post = orig
    ok("capped_at_3", len(links) == 3)


# --- firecrawl_list_links: failure modes all return None --------------------
def test_missing_key_returns_none_no_call():
    prev = os.environ.pop("FIRECRAWL_API_KEY", None)
    called = {"n": 0}

    def _post(*a, **k):
        called["n"] += 1
        return FakeResp(GOOD_PAYLOAD)

    orig = f.requests.post
    f.requests.post = _post
    try:
        out = f.firecrawl_list_links("https://trt.example/news")
    finally:
        f.requests.post = orig
        if prev is not None:
            os.environ["FIRECRAWL_API_KEY"] = prev
    ok("none_without_key", out is None)
    ok("never_spends_credit_without_key", called["n"] == 0)


def test_empty_url_returns_none():
    ok("none_on_empty_url", _with_key(lambda: f.firecrawl_list_links("")) is None)


def test_api_failure_shapes_return_none():
    orig = f.requests.post
    try:
        f.requests.post = fake_post({"success": False, "error": "rate limit"})
        ok("success_false", _with_key(lambda: f.firecrawl_list_links("https://x/news")) is None)
        f.requests.post = fake_post({"success": True, "data": {}})            # no markdown
        ok("no_markdown", _with_key(lambda: f.firecrawl_list_links("https://x/news")) is None)
        f.requests.post = fake_post({"success": True, "data": {"markdown": ""}})  # empty markdown
        ok("empty_markdown", _with_key(lambda: f.firecrawl_list_links("https://x/news")) is None)
        f.requests.post = fake_post(ValueError("not json"))                   # .json() raises
        ok("non_json", _with_key(lambda: f.firecrawl_list_links("https://x/news")) is None)
    finally:
        f.requests.post = orig


# --- fetch_web wiring -------------------------------------------------------
def test_off_uses_bs4_never_firecrawl():
    prev_enabled = f.FIRECRAWL_ENABLED
    f.FIRECRAWL_ENABLED = False
    orig_get, orig_post = f.requests.get, f.requests.post
    post_called = {"n": 0}

    def _post(*a, **k):
        post_called["n"] += 1
        return FakeResp(GOOD_PAYLOAD)

    f.requests.get = lambda url, headers=None, timeout=None: _html_resp()
    f.requests.post = _post
    try:
        arts = f.fetch_web({"id": 1, "name": "BS Source", "site_url": "https://bs.example/news"}, None, 10)
    finally:
        f.FIRECRAWL_ENABLED = prev_enabled
        f.requests.get, f.requests.post = orig_get, orig_post
    ok("bs4_built_one_article", len(arts) == 1)
    ok("bs4_kept_long_link", arts[0]["url"] == "https://bs.example/a-genuine-long-article-headline")
    ok("firecrawl_not_called_when_off", post_called["n"] == 0)


def test_on_but_firecrawl_fails_falls_back_to_bs4():
    prev_enabled = f.FIRECRAWL_ENABLED
    f.FIRECRAWL_ENABLED = True
    orig_get, orig_post = f.requests.get, f.requests.post
    f.requests.get = lambda url, headers=None, timeout=None: _html_resp()
    f.requests.post = fake_post({"success": False})   # firecrawl fails -> None -> fall back
    try:
        arts = _with_key(lambda: f.fetch_web(
            {"id": 1, "name": "Scrape Source", "site_url": "https://bs.example/news"}, None, 10))
    finally:
        f.FIRECRAWL_ENABLED = prev_enabled
        f.requests.get, f.requests.post = orig_get, orig_post
    ok("fellback_built_article", len(arts) == 1 and arts[0]["url"].endswith("headline"))


def test_on_firecrawl_success_builds_articles():
    prev_enabled = f.FIRECRAWL_ENABLED
    f.FIRECRAWL_ENABLED = True
    orig_post = f.requests.post
    f.requests.post = fake_post(GOOD_PAYLOAD)
    try:
        arts = _with_key(lambda: f.fetch_web(
            {"id": 7, "name": "TRT", "site_url": "https://trt.example/news"}, None, 10))
    finally:
        f.FIRECRAWL_ENABLED = prev_enabled
        f.requests.post = orig_post
    ok("firecrawl_built_two", len(arts) == 2)
    ok("firecrawl_article_shape", arts[0]["source_id"] == 7 and arts[0]["content_raw"] == "")


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
