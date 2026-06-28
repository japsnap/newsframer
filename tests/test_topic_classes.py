"""
Tests for NF-NEW14 topic cadence classes (agents/topic_classes.py) — pure logic.

Load-bearing guarantees:
  - no category mapped  == the OLD single-threshold backoff, exactly.
  - low_frequency (VC): wider window keeps an old post the 24h window drops; lower bar admits an
    under-scored essay; a SINGLE-article cluster is theme-eligible.
  - regular (daily news): a single-article cluster is NOT a theme (drops to highlights).

    venv\\Scripts\\python.exe tests\\test_topic_classes.py
"""
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
import topic_classes as tc  # noqa: E402

PASS = []


def ok(name, cond):
    if not cond:
        raise AssertionError(name)
    PASS.append(name)


CLASSES = {
    "regular": {"window_hours": None, "relevance_bar": None, "min_theme_articles": 2},
    "low_frequency": {"window_hours": 168, "relevance_bar": 3, "min_theme_articles": 1},
    "no_fields": {},   # a class that omits every field -> all fall back to global / defaults
}
CATMAP = {"vc": "low_frequency"}


def _mk(catmap=CATMAP, classes=CLASSES, default="regular", gw=24, gb=6, fks=True):
    return tc.TopicClasses(catmap, classes, default, gw, gb, floor_keeps_single=fks)


def _art(cat, rel=0, act=0, age_h=0.0, now=None):
    now = now or datetime(2026, 6, 25, 12, 0, 0, tzinfo=timezone.utc)
    pub = (now - timedelta(hours=age_h)).isoformat()
    return {"source_id": cat, "published_at": pub, "score": {"relevance_score": rel, "actionability": act}}


def _bundle_of(a):
    return a["source_id"]


# --- resolvers -------------------------------------------------------------
def test_class_of():
    t = _mk()
    ok("mapped", t.class_of("vc") == "low_frequency")
    ok("unmapped_default", t.class_of("crypto") == "regular")
    ok("custom_default", _mk(default="x").class_of("crypto") == "x")


def test_window_bar_min_resolvers():
    t = _mk()
    ok("regular_window_global", t.window_for("crypto") == 24)
    ok("lowfreq_window", t.window_for("vc") == 168)
    ok("regular_bar_global", t.bar_for("crypto") == 6)
    ok("lowfreq_bar", t.bar_for("vc") == 3)
    ok("regular_min2", t.min_theme_articles_for("crypto") == 2)
    ok("lowfreq_min1", t.min_theme_articles_for("vc") == 1)
    # a class that omits the fields -> global window / global bar / default min 1
    t2 = _mk(catmap={"x": "no_fields"})
    ok("nofields_window", t2.window_for("x") == 24)
    ok("nofields_bar", t2.bar_for("x") == 6)
    ok("nofields_min1", t2.min_theme_articles_for("x") == 1)


def test_max_window_and_bars_map():
    ok("max_window_lowfreq", _mk().max_window() == 168)
    ok("max_window_none_mapped", _mk(catmap={}).max_window() == 24)
    ok("bars_map_vc", _mk().bars_map() == {"vc": 3})
    ok("bars_map_empty", _mk(catmap={}).bars_map() == {})


# --- per-category window age filter ----------------------------------------
def test_filter_to_windows():
    now = datetime(2026, 6, 25, 12, 0, 0, tzinfo=timezone.utc)
    arts = [
        _art("crypto", age_h=30, now=now),    # regular, >24h -> dropped
        _art("crypto", age_h=10, now=now),    # regular, <24h -> kept
        _art("vc", age_h=30, now=now),        # low_freq, <168h -> kept (the whole point)
        _art("vc", age_h=200, now=now),       # low_freq, >168h -> dropped
        {"source_id": "crypto"},              # no date -> kept (treated fresh)
    ]
    kept = _mk().filter_to_windows(arts, now, _bundle_of)
    ages = sorted(round(tc._age_hours(a.get("published_at"), now) or -1, 0) for a in kept)
    ok("kept_count", len(kept) == 3)
    ok("kept_the_right_ones", ages == [-1.0, 10.0, 30.0])  # -1 == the dateless one


# --- filter_qualifying: no mapping == legacy single backoff ----------------
def _legacy_filter(candidates, min_rel, rel_floor, min_themes):
    def _over_bar(a, rel):
        s = a["score"]
        return (s.get("relevance_score") or 0) >= rel or (s.get("actionability") or 0) >= 2
    arts, chosen = [], min_rel
    for rel in range(min_rel, rel_floor - 1, -1):
        chosen = rel
        arts = [a for a in candidates if _over_bar(a, rel)]
        if len(arts) >= min_themes:
            break
    return arts, chosen


def test_no_mapping_equals_legacy():
    pools = [
        [_art("crypto", 7), _art("geo", 6), _art("tech", 5), _art("vc", 3)],
        [_art("crypto", 9), _art("geo", 8), _art("tech", 7)],
        [_art("crypto", 5), _art("geo", 4), _art("tech", 4)],
        [_art("geo", 1, act=2), _art("crypto", 2), _art("tech", 2)],
    ]
    t = _mk(catmap={})  # nothing mapped -> every category uses the global gate
    for i, pool in enumerate(pools):
        la, lr = _legacy_filter(pool, 6, 4, 3)
        na, nrelax = t.filter_qualifying(pool, 4, 3, _bundle_of)
        ok(f"pool{i}_same_set", {id(a) for a in na} == {id(a) for a in la})
        ok(f"pool{i}_same_threshold", (6 - nrelax) == lr)


def test_lowfreq_bar_admits_underscored():
    pool = [_art("crypto", 7), _art("geo", 6), _art("vc", 3), _art("tech", 5)]
    # vc (rel 3) is admitted at relax 0 by its bar 3; tech (regular bar 6) is not pulled in
    arts, relax = _mk().filter_qualifying(pool, 4, 3, _bundle_of)
    ok("vc_admitted", any(_bundle_of(a) == "vc" for a in arts))
    ok("no_backoff_needed", relax == 0)
    ok("tech_still_excluded", not any(_bundle_of(a) == "tech" for a in arts))


# --- eligible_clusters --------------------------------------------------------
def _cat(c):
    return c[0]["source_id"]


def test_eligible_clusters_option_b():
    # B (default): each category keeps its ONE top story (even single), extra themes need the min.
    t = _mk()
    a = [_art("crypto", 7)]                          # top crypto single -> kept (floor)
    b = [_art("crypto", 6)]                          # 2nd crypto single -> dropped (needs >=2)
    pair = [_art("crypto", 5), _art("crypto", 5)]    # crypto >=2 -> kept
    vc = [_art("vc", 4)]                             # vc single -> kept (class min 1)
    eligible, dropped = t.eligible_clusters([a, b, pair, vc], _cat)
    ok("b_top_single_kept", a in eligible)
    ok("b_second_single_dropped", b in dropped)
    ok("b_pair_kept", pair in eligible)
    ok("b_vc_single_kept", vc in eligible)
    ok("b_counts", len(eligible) == 3 and len(dropped) == 1)


def test_eligible_clusters_option_a_strict():
    # A (floor_keeps_single=False): a single-source regular story is always a highlight, never a theme.
    t = _mk(fks=False)
    a = [_art("crypto", 7)]
    pair = [_art("crypto", 5), _art("crypto", 5)]
    vc = [_art("vc", 4)]
    eligible, dropped = t.eligible_clusters([a, pair, vc], _cat)
    ok("a_single_dropped", a in dropped)
    ok("a_pair_kept", pair in eligible)
    ok("a_vc_single_still_kept", vc in eligible)     # vc class min 1 -> single allowed regardless


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
