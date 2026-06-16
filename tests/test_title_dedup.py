"""
Tests for agents/title_dedup.py (NF-NEW10 v2) — the pure logic only (no DB, no LLM):
representative-set selection (temporal earliest+developed for all; left/center/right for
bias categories), bias normalization, the confirm prompt + tolerant parse, and the
injected-LLM confirm path. No network.

    venv\\Scripts\\python.exe tests\\test_title_dedup.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
import title_dedup as td  # noqa: E402

PASS = []


def ok(name, cond):
    if not cond:
        raise AssertionError(name)
    PASS.append(name)


def m(id_, pub, src="s", clen=0):
    return {"id": id_, "published_at": pub, "source_id": src,
            "content_raw": "x" * clen, "cluster_id": "c", "title": "t"}


GEO = ["geopolitics", "pakistan"]


# --- content_len / normalize_bias -----------------------------------------
def test_content_len():
    ok("clen", td.content_len({"content_raw": "abc"}) == 3)
    ok("clen_none", td.content_len({}) == 0 and td.content_len({"content_raw": None}) == 0)


def test_normalize_bias():
    ok("left", td.normalize_bias("Left") == "left")
    ok("lean_left", td.normalize_bias("Lean Left") == "left")
    ok("right", td.normalize_bias("Lean Right") == "right")
    ok("center", td.normalize_bias("Center") == "center")
    ok("middle", td.normalize_bias("Middle") == "center")
    ok("none", td.normalize_bias(None) is None and td.normalize_bias("") is None)
    ok("unknown", td.normalize_bias("mixed") is None)


# --- temporal axis: keep up to max_keep, scaled by cluster size -----------
def test_small_cluster_keeps_all():
    # <= max_keep members -> keep everything (nothing important is cut).
    members = [m("a", "2026-06-15T01:00:00+00:00", "s1", 10),
               m("b", "2026-06-15T05:00:00+00:00", "s2", 50),
               m("c", "2026-06-15T09:00:00+00:00", "s3", 99)]
    keep, drops = td.select_representatives(members, {}, {"s1": "tech", "s2": "tech", "s3": "tech"}, GEO, max_keep=5)
    ok("keep_all_3", set(keep) == {"a", "b", "c"} and drops == [])


def test_big_temporal_cluster_capped():
    # 7 tech copies -> keep 5 = earliest + latest + 3 longest; drop the 2 shortest middles.
    members = [m("a", "2026-06-15T01:00:00+00:00", "sa", 100),
               m("b", "2026-06-15T02:00:00+00:00", "sb", 900),
               m("c", "2026-06-15T03:00:00+00:00", "sc", 200),
               m("d", "2026-06-15T04:00:00+00:00", "sd", 800),
               m("e", "2026-06-15T05:00:00+00:00", "se", 300),
               m("ff", "2026-06-15T06:00:00+00:00", "sf", 700),
               m("g", "2026-06-15T07:00:00+00:00", "sg", 500)]
    cat = {s: "tech" for s in ("sa", "sb", "sc", "sd", "se", "sf", "sg")}
    keep, drops = td.select_representatives(members, {}, cat, GEO, max_keep=5)
    ok("kept_5", len(keep) == 5)
    ok("kept_set", set(keep) == {"a", "g", "b", "d", "ff"})        # earliest + latest + 3 longest
    ok("dropped_2", {x["id"] for x in drops} == {"c", "e"})


def test_max_keep_param_caps():
    members = [m("a", "2026-06-15T01:00:00+00:00", "sa", 100),
               m("b", "2026-06-15T02:00:00+00:00", "sb", 900),
               m("c", "2026-06-15T03:00:00+00:00", "sc", 500)]
    keep, _ = td.select_representatives(members, {}, {"sa": "tech", "sb": "tech", "sc": "tech"}, GEO, max_keep=2)
    ok("max2", set(keep) == {"a", "c"})                            # earliest + latest only


# --- bias axis (geo/pakistan only) — 3 categories: left / center / right ---
# A 7-copy cluster where the temporal detail-fill (top-5) MISSES the lone, short right source.
_MIX = [("a", "01", "sL1", 100), ("r", "02", "sR", 50), ("b", "03", "sL2", 900),
        ("c", "04", "sC", 800), ("d", "05", "sL3", 700), ("e", "06", "sL4", 400),
        ("g", "07", "sL5", 600)]
_BIAS = {"sL1": "left", "sL2": "left", "sL3": "left", "sL4": "left", "sL5": "left", "sC": "center", "sR": "right"}


def _mix(category):
    members = [m(i, f"2026-06-15T{h}:00:00+00:00", s, c) for i, h, s, c in _MIX]
    return members, {s: category for _, _, s, _ in _MIX}


def test_bias_axis_adds_missing_lean():
    members, cat = _mix("geopolitics")
    keep, drops = td.select_representatives(members, _BIAS, cat, GEO, max_keep=5)
    ok("right_rep_added", "r" in keep)                  # temporal missed it; the bias axis added it
    ok("kept_6", len(keep) == 6)
    ok("dropped_e_only", {x["id"] for x in drops} == {"e"})


def test_bias_skipped_for_non_bias_category():
    members, cat = _mix("tech")                         # same cluster, but tech -> NO bias axis
    keep, _ = td.select_representatives(members, _BIAS, cat, GEO, max_keep=5)
    ok("tech_no_right_forced", "r" not in keep and len(keep) == 5)


def test_bias_missing_side_not_forced():
    members = [m("a", "2026-06-15T01:00:00+00:00", "sL", 100), m("b", "2026-06-15T09:00:00+00:00", "sC", 50)]
    cat = {"sL": "pakistan", "sC": "pakistan"}
    keep, drops = td.select_representatives(members, {"sL": "left", "sC": "center"}, cat, GEO, max_keep=5)
    ok("missing_side", set(keep) == {"a", "b"} and drops == [])   # both kept, no right invented


def test_bias_unseeded_degrades_to_temporal():
    members, cat = _mix("geopolitics")
    keep, _ = td.select_representatives(members, {}, cat, GEO, max_keep=5)   # bias_of empty -> unseeded
    ok("unseeded_no_right", "r" not in keep and len(keep) == 5)   # falls back to temporal-only


def test_select_singleton_and_empty():
    one, d1 = td.select_representatives([m("x", "2026-06-15T00:00:00+00:00")])
    ok("single", one == ["x"] and d1 == [])
    z, d0 = td.select_representatives([])
    ok("empty", z == [] and d0 == [])


# --- confirm prompt / parse / injected LLM --------------------------------
def test_build_confirm_prompt():
    p = td.build_confirm_prompt(["Iran deal signed", "US and Iran reach pact"])
    ok("lists_titles", "Iran deal signed" in p and "US and Iran reach pact" in p)
    ok("asks_same_event", "same_event" in p and "SAME" in p)


def test_parse_confirm():
    ok("true", td.parse_confirm('{"same_event": true}') is True)
    ok("false", td.parse_confirm('{"same_event": false}') is False)
    ok("yes_str", td.parse_confirm('{"same_event": "yes"}') is True)
    ok("fenced", td.parse_confirm('```json\n{"same_event": true}\n```') is True)
    ok("garbage_false", td.parse_confirm("not json at all") is False)
    ok("missing_false", td.parse_confirm('{"other": true}') is False)
    ok("int_conservative", td.parse_confirm('{"same_event": 1}') is False)


def _fake(content):
    class _M:
        def __init__(s, c): s.message = type("x", (), {"content": c})()
    class _R:
        def __init__(s, c): s.choices = [_M(c)]
    def _call(**kwargs):
        return _R(content)
    return _call


def test_confirm_same_event_injected():
    ok("confirm_true", td.confirm_same_event(["a", "b"], "m", 0, 20, _completion=_fake('{"same_event": true}')) is True)
    ok("confirm_false", td.confirm_same_event(["a", "b"], "m", 0, 20, _completion=_fake('{"same_event": false}')) is False)


def test_confirm_error_keeps_all():
    def _boom(**kwargs):
        raise RuntimeError("api down")
    ok("error_false", td.confirm_same_event(["a", "b"], "m", 0, 20, _completion=_boom) is False)


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
