"""
Tests for the writer's pure clustering/selection helpers (agents/writer.py):
composite_score, cluster_by_topic_overlap, pick_highlights.

These were untested. cluster_by_topic_overlap underpins the per-bundle theme-floor
guarantee (a lone low-frequency article must survive as a SINGLETON cluster, or the
floor in bundle_floors can never promote it). Pinning that here protects NF-A1/§8.6.

No DB, no LLM — pure logic over article dicts.

    venv\\Scripts\\python.exe tests\\test_clustering.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
import writer as w  # noqa: E402

PASS = []


def ok(name, cond):
    if not cond:
        raise AssertionError(name)
    PASS.append(name)


def art(id, topics, rel=5, act=0):
    return {"id": id, "title": f"t-{id}", "score": {"topics": topics, "relevance_score": rel, "actionability": act}}


# --- composite_score -------------------------------------------------------
def test_composite_score_formula():
    ok("composite", w.composite_score(art("a", [], rel=8, act=2)) == 8 * 10 + 2 * 15)
    ok("composite_zero", w.composite_score(art("a", [], rel=0, act=0)) == 0)
    ok("composite_none_safe", w.composite_score({"score": {}}) == 0)


# --- cluster_by_topic_overlap: the singleton guarantee ---------------------
def test_lone_article_survives_as_singleton():
    themes, leftovers = w.cluster_by_topic_overlap([art("solo", ["niche"])], 5, 6)
    ok("singleton_one_cluster", len(themes) == 1)
    ok("singleton_one_article", len(themes[0]) == 1 and themes[0][0]["id"] == "solo")


def test_no_topics_still_clusters():
    themes, _ = w.cluster_by_topic_overlap([art("notopics", [])], 5, 6)
    ok("no_topics_kept", len(themes) == 1 and themes[0][0]["id"] == "notopics")


# --- NF-NEW10c: build_articles_block tags one-sided themes for the LLM -----
def test_articles_block_coverage_tag():
    clusters = [[art("a", ["x"])], [art("b", ["y"])]]
    tagged = w.build_articles_block(clusters, {}, {}, coverage_notes=["left", None])
    ok("left_tag_present", "[ONE-SIDED COVERAGE: left]" in tagged)
    ok("cluster1_tagged", "Cluster 1 (1 articles) [ONE-SIDED COVERAGE: left]" in tagged)
    ok("cluster2_untagged", "Cluster 2 (1 articles) ===" in tagged)
    untagged = w.build_articles_block(clusters, {}, {})   # no coverage_notes -> no marker at all
    ok("no_marker_by_default", "ONE-SIDED COVERAGE" not in untagged)


# --- cluster_by_topic_overlap: grouping rules ------------------------------
def test_two_shared_topics_group():
    a = art("a", ["x", "y", "z"], rel=9)
    b = art("b", ["x", "y", "q"], rel=8)
    themes, _ = w.cluster_by_topic_overlap([a, b], 5, 6)
    ok("two_shared_one_cluster", len(themes) == 1 and len(themes[0]) == 2)


def test_one_shared_with_small_set_groups():
    # shared>=1 AND one side has <=2 topics -> grouped
    a = art("a", ["x", "y"], rel=9)
    b = art("b", ["x", "p", "q"], rel=8)
    themes, _ = w.cluster_by_topic_overlap([a, b], 5, 6)
    ok("weak_overlap_small_set_groups", len(themes) == 1)


def test_one_shared_both_large_sets_do_not_group():
    # shared==1 and BOTH sides have >2 topics -> separate clusters
    a = art("a", ["x", "m", "n"], rel=9)
    b = art("b", ["x", "p", "q"], rel=8)
    themes, _ = w.cluster_by_topic_overlap([a, b], 5, 6)
    ok("weak_overlap_large_sets_split", len(themes) == 2)


def test_max_per_theme_caps_cluster_size():
    arts = [art(f"a{i}", ["x", "y"], rel=9 - i) for i in range(4)]  # all mutually overlapping
    themes, _ = w.cluster_by_topic_overlap(arts, 5, 2)
    ok("cap_size", all(len(c) <= 2 for c in themes))


# --- ranking + max_themes truncation + leftovers ---------------------------
def test_ranked_by_composite_and_truncated():
    hi = art("hi", ["a1"], rel=10)     # composite 100
    mid = art("mid", ["b1"], rel=6)    # composite 60
    lo = art("lo", ["c1"], rel=3)      # composite 30
    themes, leftovers = w.cluster_by_topic_overlap([lo, mid, hi], 2, 6)
    ok("top_first", themes[0][0]["id"] == "hi")
    ok("two_themes", len(themes) == 2)
    ok("lo_is_leftover", any(a["id"] == "lo" for a in leftovers))


# --- pick_highlights -------------------------------------------------------
def test_pick_highlights_filters_and_ranks():
    leftovers = [art("h1", [], rel=9), art("low", [], rel=5), art("h2", [], rel=10)]
    picks = w.pick_highlights(leftovers, count=5, min_relevance=8)
    ids = [p["id"] for p in picks]
    ok("highlights_drop_below_min", "low" not in ids)
    ok("highlights_ranked", ids[0] == "h2")
    ok("highlights_count", len(ids) == 2)


def test_pick_highlights_respects_count():
    leftovers = [art(f"h{i}", [], rel=9) for i in range(6)]
    picks = w.pick_highlights(leftovers, count=3, min_relevance=8)
    ok("highlights_capped", len(picks) == 3)


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
