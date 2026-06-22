"""
Tests for item 5 (2026-06-22) — fetcher.resolve_fetch_caps (three tiers) + fetch_rss newest-first.
Pure: no network, no DB. full=50 / normal=30 (LIVE) / light=10; unknown/missing -> normal. fetch_rss
must keep the NEWEST N per source (RSS feed order is not always newest-first).

    venv\\Scripts\\python.exe tests\\test_fetcher_profile.py
"""
import os
import sys
import types
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
import fetcher as f  # noqa: E402

PASS = []


def ok(name, cond):
    if not cond:
        raise AssertionError(name)
    PASS.append(name)


LIVE_CFG = {
    "fetch_profile": "normal",
    "fetch_profiles": {"full": 50, "normal": 30, "light": 10},
    "fetch_safety_ceiling": 3000,
}


def test_normal_is_live_30():
    profile, mps, ceil = f.resolve_fetch_caps(LIVE_CFG)
    ok("normal_label", profile == "normal")
    ok("normal_30", mps == 30)
    ok("ceiling_3000", ceil == 3000)


def test_full_is_50():
    profile, mps, _ = f.resolve_fetch_caps(dict(LIVE_CFG, fetch_profile="full"))
    ok("full_50", profile == "full" and mps == 50)


def test_light_is_10():
    profile, mps, _ = f.resolve_fetch_caps(dict(LIVE_CFG, fetch_profile="light"))
    ok("light_10", profile == "light" and mps == 10)


def test_case_and_space_insensitive():
    profile, mps, _ = f.resolve_fetch_caps(dict(LIVE_CFG, fetch_profile="  FULL "))
    ok("full_normalized", profile == "full" and mps == 50)


def test_unknown_falls_back_to_normal():
    profile, mps, _ = f.resolve_fetch_caps(dict(LIVE_CFG, fetch_profile="turbo"))
    ok("unknown_normal", profile == "normal" and mps == 30)


def test_missing_profile_defaults_normal():
    profile, mps, _ = f.resolve_fetch_caps({"fetch_profiles": {"full": 50, "normal": 30, "light": 10}})
    ok("missing_normal", profile == "normal" and mps == 30)


def test_empty_config_safe_defaults():
    profile, mps, ceil = f.resolve_fetch_caps({})
    ok("empty_normal", profile == "normal" and mps == 30 and ceil == 3000)


def test_none_values_use_defaults():
    profile, mps, ceil = f.resolve_fetch_caps(
        {"fetch_profile": None, "fetch_profiles": None, "fetch_safety_ceiling": None})
    ok("none_normal", profile == "normal" and mps == 30 and ceil == 3000)


def test_ceiling_is_int():
    _, _, ceil = f.resolve_fetch_caps(dict(LIVE_CFG, fetch_safety_ceiling="3000"))
    ok("ceiling_int", ceil == 3000 and isinstance(ceil, int))


def test_tolerant_of_broken_config():
    class Boom:
        def get(self, *a):
            raise RuntimeError("boom")
    profile, mps, ceil = f.resolve_fetch_caps(Boom())
    ok("broken_safe", profile == "normal" and mps == 30 and ceil == 3000)


class _Entry(dict):
    """dict that ALSO supports attribute access (feedparser entries do both)."""
    def __getattr__(self, k):
        try:
            return self[k]
        except KeyError:
            raise AttributeError(k)


def test_fetch_rss_keeps_newest_n_in_order():
    now = datetime.now(timezone.utc)

    def mk(title, mins_ago):
        dt = now - timedelta(minutes=mins_ago)
        return _Entry({"title": title, "link": "http://x/" + title, "summary": "s",
                       "published_parsed": dt.timetuple()})

    # feed order is deliberately NOT newest-first
    feed = types.SimpleNamespace(entries=[mk("old", 300), mk("new", 5), mk("mid", 120)])
    orig = f.feedparser.parse
    f.feedparser.parse = lambda url: feed
    try:
        arts = f.fetch_rss({"id": "s1", "name": "S", "rss_url": "http://x"},
                           now - timedelta(hours=24), 2)
    finally:
        f.feedparser.parse = orig
    ok("rss_capped_to_2", len(arts) == 2)
    ok("rss_newest_first", arts[0]["title"] == "new" and arts[1]["title"] == "mid")


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
