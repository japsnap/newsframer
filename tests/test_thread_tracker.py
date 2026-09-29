"""
Tests for agents/thread_tracker.py (NF-C1, spec §4.4) — the PURE sequencing core.
No DB, no live LLM (Stage A is exercised with a fake completion). Pins: the Monday-reset
boundary, quantity parsing, the per-type delta classifier (all 7 types + the data-to-data
guard), note formatting, trajectory cap, section render/splice, Stage-0 match, story grouping.

    venv\\Scripts\\python.exe tests\\test_thread_tracker.py
"""
import os
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
import thread_tracker as tt  # noqa: E402

PASS = []


def ok(name, cond):
    if not cond:
        raise AssertionError(name)
    PASS.append(name)


# --- Monday-06:00-JST reset boundary (§4.2) -------------------------------
def test_week_start_boundary():
    # Wed 2026-06-17 13:00 UTC -> JST week's Monday = 2026-06-15
    ok("midweek", tt.week_start_key(datetime(2026, 6, 17, 13, 0, tzinfo=timezone.utc)) == "2026-06-15")
    # Monday 2026-06-15 05:00 JST (= Sun 20:00 UTC) is BEFORE the 06:00 reset -> previous Monday
    ok("before_reset", tt.week_start_key(datetime(2026, 6, 14, 20, 0, tzinfo=timezone.utc)) == "2026-06-08")
    # Monday 2026-06-15 06:00 JST (= 21:00 UTC Sun) is AT the reset -> new chain
    ok("at_reset", tt.week_start_key(datetime(2026, 6, 14, 21, 0, tzinfo=timezone.utc)) == "2026-06-15")


# --- parse_quantity --------------------------------------------------------
def test_parse_quantity():
    ok("plain", tt.parse_quantity("47") == (47.0, None))
    ok("with_unit", tt.parse_quantity("47 dead") == (47.0, "dead"))
    ok("currency_m", tt.parse_quantity("$5M") == (5_000_000.0, None))
    ok("words_million", tt.parse_quantity("5 million") == (5_000_000.0, None))
    ok("commas", tt.parse_quantity("20,000 acres") == (20000.0, "acres"))
    ok("percent", tt.parse_quantity("40%") == (40.0, "%"))
    ok("int", tt.parse_quantity(12) == (12.0, None))
    ok("none", tt.parse_quantity("no number") is None)
    ok("blank", tt.parse_quantity("") is None and tt.parse_quantity(None) is None)


def test_is_material_numeric():
    ok("abs_clears", tt.is_material_numeric(2, 10, 0.15, 1.0) is True)
    ok("below_both", tt.is_material_numeric(100, 101, 0.15, 5.0) is False)
    ok("abs_big", tt.is_material_numeric(100, 120, 0.15, 5.0) is True)
    ok("zero_base", tt.is_material_numeric(0, 1, 0.15, 5.0) is False)
    # NF-C1a: abs_thresh <= 0 DISABLES the absolute bar -> percentage-only (crypto/price)
    ok("abs_disabled_pct_clears", tt.is_material_numeric(60000, 66000, 0.10, 0) is True)   # 10%
    ok("abs_disabled_pct_below", tt.is_material_numeric(60000, 65000, 0.10, 0) is False)   # 8.3%
    ok("abs_disabled_tiny_wiggle", tt.is_material_numeric(60000, 60500, 0.10, 0) is False)  # 0.8%


# --- NF-C1a: per-category materiality override + crypto 10% gating ---------
def test_resolve_materiality():
    cfg = {"sequencing_materiality": {"magnitude_abs": 1, "magnitude_pct": 0.15},
           "sequencing_materiality_overrides": {"crypto": {"magnitude_pct": 0.10, "magnitude_abs": 0}}}
    m = tt.resolve_materiality(cfg, "crypto")
    ok("override_applied", m["magnitude_pct"] == 0.10 and m["magnitude_abs"] == 0)
    ok("override_other_category", tt.resolve_materiality(cfg, "geopolitics")["magnitude_pct"] == 0.15)
    ok("override_none_category", tt.resolve_materiality(cfg, None)["magnitude_pct"] == 0.15)
    ok("override_missing_block", tt.resolve_materiality({}, "crypto") == {})


def test_crypto_price_gating():
    mat = {"magnitude_pct": 0.10, "magnitude_abs": 0}      # the resolved crypto bars
    ok("crypto_10pct_material", tt.classify_delta(P("60000"), F("66000", unit="USD"), mat) is not None)
    ok("crypto_below_10pct", tt.classify_delta(P("60000"), F("65000", unit="USD"), mat) is None)
    ok("crypto_tiny_wiggle", tt.classify_delta(P("65000"), F("66000", unit="USD"), mat) is None)  # 1.5%
    # the SAME move under the GLOBAL bars (abs=1) would have fired -> proves the override matters
    ok("global_would_fire", tt.classify_delta(P("65000"), F("66000"),
                                              {"magnitude_abs": 1, "magnitude_pct": 0.15}) is not None)


def test_humanize():
    ok("hum_k", tt._humanize(66000) == "66K")
    ok("hum_k60", tt._humanize(60000) == "60K")
    ok("hum_m", tt._humanize(1_500_000) == "1.5M")
    ok("hum_small", tt._humanize(47) == "47")
    ok("hum_neg", tt._humanize(-5000) == "-5K")


def test_price_format():
    note = tt.format_shift_note("Bitcoin", {"type": "magnitude", "old": "60000", "new": "66000",
                                            "unit": "USD", "since": "2026-06-16T00:00:00Z"},
                                price_units=["usd", "$"])
    ok("price_humanized", "$60K" in note and "$66K" in note)
    ok("price_pct", "+10%" in note)
    ok("price_phrasing", "was $60K" in note and "now $66K" in note)
    # a non-currency numeric note is UNCHANGED (compact arrow) — no format regression
    arrow = tt.format_shift_note("Toll", {"type": "cumulative", "old": "12", "new": "47",
                                          "unit": "dead", "since": "2026-06-16T00:00:00Z"})
    ok("nonprice_arrow", "→" in arrow and "dead" in arrow and "$" not in arrow)


def test_brief_stories_category():
    clusters = [[{"id": "a1", "cluster_id": "c1", "title": "BTC up", "content_raw": "x", "source_id": "s1"},
                 {"id": "a2", "cluster_id": "c1", "title": "BTC up2", "content_raw": "y", "source_id": "s2"}],
                [{"id": "a3", "cluster_id": None, "title": "Solo", "content_raw": "z", "source_id": "s9"}]]
    stories = tt.brief_stories(clusters, {"s1": "crypto", "s2": "crypto", "s9": "geopolitics"})
    grp = [s for s in stories if s["has_cluster"]][0]
    solo = [s for s in stories if not s["has_cluster"]][0]
    ok("story_category_majority", grp["category"] == "crypto")
    ok("story_category_single", solo["category"] == "geopolitics")
    ok("story_category_none_without_map", tt.brief_stories(clusters)[0]["category"] is None)


# --- classify_delta: all 7 types + guards ---------------------------------
def P(value, dtype="magnitude", ids=("old1",), as_of="2026-06-16T00:00:00Z"):
    return {"value": value, "delta_type": dtype, "article_ids": list(ids), "as_of": as_of}


def F(value, dtype="magnitude", ids=("new1",), unit=None):
    return {"value": value, "delta_type": dtype, "article_ids": list(ids), "unit": unit}


def test_no_prior_no_delta():
    ok("no_prior", tt.classify_delta(None, F("10")) is None)


def test_magnitude():
    d = tt.classify_delta(P("2"), F("10"))
    ok("mag_material", d is not None and d["type"] == "magnitude" and d["old"] == "2" and d["new"] == "10")
    ok("mag_ids_both", d["old_ids"] == ["old1"] and d["new_ids"] == ["new1"])  # data-to-data traceability
    ok("mag_noop", tt.classify_delta(P("100"), F("100")) is None)
    ok("mag_below_bar",
       tt.classify_delta(P("100"), F("101"), {"magnitude_abs": 5, "magnitude_pct": 0.15}) is None)


def test_cumulative_must_climb():
    ok("tally_up", tt.classify_delta(P("12", "cumulative"), F("47", "cumulative")) is not None)
    ok("tally_down", tt.classify_delta(P("47", "cumulative"), F("12", "cumulative")) is None)
    ok("tally_equal", tt.classify_delta(P("47", "cumulative"), F("47", "cumulative")) is None)


def test_status_lifecycle():
    d = tt.classify_delta(P("proposed", "status"), F("passed committee", "status"))
    ok("status_change", d is not None and d["type"] == "status")
    ok("status_same", tt.classify_delta(P("passed", "status"), F("passed", "status")) is None)


def test_reversal():
    d = tt.classify_delta(P("no casualties", "reversal"), F("12 dead", "reversal"))
    ok("reversal", d is not None and d["type"] == "reversal")


def test_scope_and_attribution():
    ok("scope", tt.classify_delta(P("Gaza", "scope"), F("Gaza+Lebanon", "scope")) is not None)
    ok("attribution",
       tt.classify_delta(P("unknown", "attribution"), F("claimed by group X", "attribution")) is not None)


def test_forecast_vs_actual():
    d = tt.classify_delta(P("-25bp", "forecast"), F("-50bp", "forecast"))
    ok("forecast", d is not None and d["type"] == "forecast")


def test_numeric_requires_parseable_numbers():
    # a numeric type whose values don't parse as numbers -> skip (no string guess, no noise)
    ok("num_unparseable_skip", tt.classify_delta(P("steady", "magnitude"), F("surging", "magnitude")) is None)


def test_cross_family_flip_is_skipped():
    # the real-data noise case: a status prior + a numeric new value ("within 24 hours") -> skip
    ok("status_to_num_skip", tt.classify_delta(P("reached", "status"), F("24", "magnitude")) is None)
    ok("num_to_status_skip", tt.classify_delta(P("12", "cumulative"), F("signed", "status")) is None)


def test_delta_always_carries_both_id_sides():
    d = tt.classify_delta(P("12", "cumulative", ids=("o1", "o2")), F("47", "cumulative", ids=("n1",)))
    ok("both_ids", d is not None and d["old_ids"] == ["o1", "o2"] and d["new_ids"] == ["n1"])
    cat = tt.classify_delta(P("proposed", "status", ids=("o1",)), F("passed", "status", ids=("n1", "n2")))
    ok("cat_both_ids", cat["old_ids"] == ["o1"] and cat["new_ids"] == ["n1", "n2"])


def test_clean_label_word_boundary():
    long = "US, Iran reach preliminary agreement to end war, signing set for Friday morning"
    lbl = tt._clean_label(long)
    ok("label_short", len(lbl) <= 48 and not lbl.endswith(":") and " " in lbl)
    ok("label_no_midword", not long[len(lbl)].isalpha() if len(lbl) < len(long) else True)
    ok("label_empty", tt._clean_label("") == "story" and tt._clean_label(None) == "story")


# --- format_shift_note -----------------------------------------------------
def test_format_note():
    note = tt.format_shift_note("Gaza toll", {"type": "cumulative", "old": "12", "new": "47",
                                              "unit": "dead", "since": "2026-06-16T00:00:00Z"})
    ok("note_arrow", "12" in note and "47" in note and "→" in note and "dead" in note)
    rev = tt.format_shift_note("Deal", {"type": "reversal", "old": "reached", "new": "collapsed",
                                        "since": "2026-06-16T00:00:00Z"})
    ok("note_reversal", "reversed" in rev and "reached" in rev and "collapsed" in rev)
    linked = tt.format_shift_note("X", {"type": "status", "old": "a", "new": "b", "since": "x"},
                                  source_link="[Reuters](http://r.example)")
    ok("note_link", linked.endswith("[Reuters](http://r.example)"))


# --- trajectory cap / section render / splice -----------------------------
def test_cap_points():
    ok("cap", tt.cap_points([1, 2, 3, 4], 3) == [2, 3, 4])
    ok("cap_min1", tt.cap_points([1, 2, 3], 0) == [3])
    ok("cap_empty", tt.cap_points([], 3) == [])


def test_render_section():
    ok("render_empty", tt.render_what_changed_section([]) == "")
    s = tt.render_what_changed_section(["a", "", "b"])
    ok("render_lines", s == tt.WHAT_CHANGED_HEADING + "\n- a\n- b")


def test_splice():
    text = "## Theme\nbody\n\n---\n_footer_"
    out = tt.splice_what_changed(text, "## 📈 What Changed\n- x")
    ok("splice_before_footer", "What Changed" in out and out.index("What Changed") < out.index("---"))
    ok("splice_keeps_footer", out.endswith("_footer_"))
    ok("splice_empty_noop", tt.splice_what_changed(text, "") == text)
    nofoot = tt.splice_what_changed("just text", "## 📈 What Changed\n- x")
    ok("splice_append", "What Changed" in nofoot)


# --- Stage 0 match (pure over loaded threads) -----------------------------
def test_match_thread():
    threads = [{"id": "t1", "embedding": [1.0, 0.0]}, {"id": "t2", "embedding": [0.0, 1.0]}]
    m, s = tt.match_thread([0.99, 0.01], threads, 0.83)
    ok("match_hit", m is not None and m["id"] == "t1" and s > 0.83)
    m2, s2 = tt.match_thread([0.7, 0.7], threads, 0.95)
    ok("match_below_threshold", m2 is None)
    m3, _ = tt.match_thread(None, threads, 0.5)
    ok("match_no_vec", m3 is None)


# --- story grouping --------------------------------------------------------
def test_brief_stories():
    clusters = [
        [{"id": "a1", "cluster_id": "c1", "title": "Story A", "content_raw": "x"},
         {"id": "a2", "cluster_id": "c1", "title": "Story A dup", "content_raw": "y"}],
        [{"id": "a3", "cluster_id": None, "title": "Single", "content_raw": "z"}],
    ]
    stories = tt.brief_stories(clusters)
    c1 = [s for s in stories if s["has_cluster"]][0]
    ok("group_cluster", set(c1["article_ids"]) == {"a1", "a2"} and c1["theme_idx"] == 0)
    single = [s for s in stories if not s["has_cluster"]][0]
    ok("group_single", single["article_ids"] == ["a3"] and single["has_cluster"] is False)


def test_story_vector_centroid():
    embs = {"a1": [2.0, 0.0], "a2": [0.0, 2.0]}
    v = tt._story_vector({"article_ids": ["a1", "a2"]}, embs)
    ok("centroid", v == [1.0, 1.0])
    ok("centroid_missing", tt._story_vector({"article_ids": ["zz"]}, embs) is None)


# --- Stage A extraction with a FAKE completion (no live LLM) ---------------
class _Resp:
    def __init__(self, content):
        self.choices = [type("C", (), {"message": type("M", (), {"content": content})()})()]


def test_extract_fact_attaches_real_ids():
    fake = lambda **kw: _Resp('{"delta_type":"cumulative","value":"47","unit":"dead",'
                              '"short_fact":"toll 47","confidence":0.9}')
    fact = tt.extract_fact("Gaza", ["txt"], ["real-id-1", "real-id-2"], "m", 0, 50, _completion=fake)
    ok("extract_value", fact["value"] == "47" and fact["delta_type"] == "cumulative")
    ok("extract_ids_from_caller", fact["article_ids"] == ["real-id-1", "real-id-2"])  # NOT model-supplied


def test_extract_fact_rejects_junk():
    ok("extract_bad_json", tt.extract_fact("X", ["t"], ["i"], "m", 0, 50,
                                           _completion=lambda **kw: _Resp("not json")) is None)
    ok("extract_empty_value", tt.extract_fact("X", ["t"], ["i"], "m", 0, 50,
        _completion=lambda **kw: _Resp('{"delta_type":"magnitude","value":""}')) is None)
    ok("extract_bad_type", tt.extract_fact("X", ["t"], ["i"], "m", 0, 50,
        _completion=lambda **kw: _Resp('{"delta_type":"weather","value":"9"}')) is None)


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
