"""
Tests for the deduplicator's PURE core — the clustering math that decides every dedup
(and the cluster_id NF-NEW10 reuses). No network, no DB. Covers: embedding parse, cosine
similarity, candidate pairs, union-find clustering, time span, price-event classification,
min pairwise similarity, and primary selection.

    venv\\Scripts\\python.exe tests\\test_deduplicator.py
"""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
import deduplicator as d  # noqa: E402

PASS = []


def ok(name, cond):
    if not cond:
        raise AssertionError(name)
    PASS.append(name)


def art(id_, pub=None, title="", content="", emb=None):
    return {"id": id_, "published_at": pub, "title": title, "content_raw": content, "embedding": emb}


# --- parse_embedding -------------------------------------------------------
def test_parse_embedding():
    ok("none", d.parse_embedding(None) is None)
    ok("list", d.parse_embedding([1, 2.5, 3]) == [1.0, 2.5, 3.0])
    ok("string", d.parse_embedding("[1, 2, 3]") == [1.0, 2.0, 3.0])
    ok("empty_string", d.parse_embedding("[]") is None and d.parse_embedding("") is None)
    ok("other_type", d.parse_embedding(42) is None)


# --- cosine_similarity -----------------------------------------------------
def test_cosine_similarity():
    ok("identical", abs(d.cosine_similarity([1, 0], [1, 0]) - 1.0) < 1e-9)
    ok("orthogonal", d.cosine_similarity([1, 0], [0, 1]) == 0.0)
    ok("parallel", abs(d.cosine_similarity([1, 1], [2, 2]) - 1.0) < 1e-9)
    ok("mismatched_len", d.cosine_similarity([1, 2], [1]) == 0.0)
    ok("zero_vec", d.cosine_similarity([0, 0], [1, 1]) == 0.0)
    ok("empty", d.cosine_similarity([], []) == 0.0)


# --- find_candidate_pairs --------------------------------------------------
def test_find_candidate_pairs():
    arts = [art("a", emb=[1, 0]), art("b", emb=[1, 0]), art("c", emb=[0, 1]), art("d", emb=None)]
    pairs = d.find_candidate_pairs(arts, 0.85)
    ok("one_pair", len(pairs) == 1)
    ok("pair_is_ab", pairs[0][0] == 0 and pairs[0][1] == 1)        # a,b identical
    ok("none_emb_skipped", all(d not in (p[0], p[1]) for p in pairs for d in (3,)))


# --- build_clusters (union-find) ------------------------------------------
def test_build_clusters_transitive():
    arts = [art("0"), art("1"), art("2"), art("3")]
    clusters = d.build_clusters(arts, [(0, 1, 0.9), (1, 2, 0.9)])    # 0-1-2 transitively joined
    ok("one_cluster", len(clusters) == 1)
    members = sorted(next(iter(clusters.values())))
    ok("transitive_members", members == [0, 1, 2])                  # 3 is a singleton -> dropped


def test_build_clusters_two_groups_and_singletons():
    arts = [art(str(i)) for i in range(5)]
    clusters = d.build_clusters(arts, [(0, 1, 0.9), (2, 3, 0.9)])
    ok("two_clusters", len(clusters) == 2)
    ok("singleton_dropped", all(4 not in m for m in clusters.values()))
    ok("no_pairs_empty", d.build_clusters(arts, []) == {})


# --- parse_dt / cluster_time_span_hours -----------------------------------
def test_parse_dt():
    ok("none", d.parse_dt(None) is None)
    ok("zulu", d.parse_dt("2026-06-15T01:00:00Z").hour == 1)
    ok("offset", d.parse_dt("2026-06-15T01:00:00+00:00").hour == 1)
    now = datetime(2026, 6, 15, tzinfo=timezone.utc)
    ok("passthrough", d.parse_dt(now) is now)


def test_cluster_time_span():
    members = [art("a", "2026-06-15T01:00:00+00:00"), art("b", "2026-06-15T06:00:00+00:00")]
    ok("span_5h", abs(d.cluster_time_span_hours(members) - 5.0) < 1e-6)
    ok("single_zero", d.cluster_time_span_hours([art("a", "2026-06-15T01:00:00+00:00")]) == 0.0)
    ok("no_times_zero", d.cluster_time_span_hours([art("a"), art("b")]) == 0.0)


# --- has_price_event_keywords / classify_cluster --------------------------
def test_price_event_keywords():
    ok("price_word", d.has_price_event_keywords(art("a", title="Bitcoin price surges to new high")) is True)
    ok("percent", d.has_price_event_keywords(art("a", title="Index up 3% on the day")) is True)
    ok("neutral_false", d.has_price_event_keywords(art("a", title="EU debates long-term policy reform")) is False)


def test_classify_cluster():
    recent = [art("a", "2026-06-15T01:00:00+00:00", title="Bitcoin surges"),
              art("b", "2026-06-15T03:00:00+00:00", title="BTC rally continues")]   # 2h span, keyword
    ok("price_event", d.classify_cluster(recent, 12) == "price_event")
    wide = [art("a", "2026-06-15T01:00:00+00:00", title="Bitcoin surges"),
            art("b", "2026-06-16T20:00:00+00:00", title="BTC rally")]                # >12h span
    ok("wide_is_analysis", d.classify_cluster(wide, 12) == "analysis")
    neutral = [art("a", "2026-06-15T01:00:00+00:00", title="Policy talks"),
               art("b", "2026-06-15T02:00:00+00:00", title="Diplomatic meeting")]    # no keyword
    ok("no_keyword_analysis", d.classify_cluster(neutral, 12) == "analysis")


# --- min_pairwise_similarity ----------------------------------------------
def test_min_pairwise_similarity():
    members = [art("a"), art("b"), art("c")]
    pim = {("a", "b"): 0.95, ("a", "c"): 0.88, ("x", "y"): 0.50}    # ('x','y') is outside the cluster
    ok("min_within", abs(d.min_pairwise_similarity(members, pim) - 0.88) < 1e-9)
    ok("no_pairs_is_1", d.min_pairwise_similarity([art("z")], pim) == 1.0)


# --- pick_primary ----------------------------------------------------------
def test_pick_primary():
    members = [art("a", "2026-06-15T01:00:00+00:00"),
               art("b", "2026-06-15T09:00:00+00:00"),
               art("c", "2026-06-15T05:00:00+00:00")]
    ok("price_event_latest", d.pick_primary(members, "price_event")["id"] == "b")    # latest
    ok("analysis_earliest", d.pick_primary(members, "analysis")["id"] == "a")          # earliest = originator


def test_build_text_for_embedding():
    t = d.build_text_for_embedding(art("a", title="Headline", content="Body text here"))
    ok("title_and_body", "Headline" in t and "Body text here" in t)
    ok("empty_safe", d.build_text_for_embedding(art("a")) == "")


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
