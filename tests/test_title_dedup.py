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


# --- temporal axis (every topic): earliest + most-developed ---------------
def test_temporal_keeps_earliest_and_latest():
    members = [m("a", "2026-06-15T01:00:00+00:00", "s1"),
               m("b", "2026-06-15T05:00:00+00:00", "s2"),
               m("c", "2026-06-15T09:00:00+00:00", "s3")]
    cat = {"s1": "tech", "s2": "tech", "s3": "tech"}
    keep, drops = td.select_representatives(members, {}, cat, GEO)
    ok("temporal_keep2", set(keep) == {"a", "c"})              # earliest + latest
    ok("temporal_drop_mid", [d["id"] for d in drops] == ["b"])


def test_developed_tiebreak_by_length():
    members = [m("a", "2026-06-15T01:00:00+00:00", "s1", clen=10),
               m("b", "2026-06-15T09:00:00+00:00", "s2", clen=50),
               m("c", "2026-06-15T09:00:00+00:00", "s3", clen=500)]   # same latest time, longest body
    keep, drops = td.select_representatives(members, {}, {"s1": "tech", "s2": "tech", "s3": "tech"}, GEO)
    ok("dev_longest", set(keep) == {"a", "c"})                 # a earliest, c latest+longest
    ok("dev_drop_b", [d["id"] for d in drops] == ["b"])


# --- bias axis (geo/pakistan only) ----------------------------------------
def test_bias_axis_left_center_right():
    members = [m("a", "2026-06-15T01:00:00+00:00", "sL"),   # left, earliest
               m("b", "2026-06-15T05:00:00+00:00", "sC"),   # center (earlier)
               m("c", "2026-06-15T09:00:00+00:00", "sR"),   # right, latest -> developed
               m("d", "2026-06-15T06:00:00+00:00", "sC2")]  # center (later -> the center rep)
    cat = {k: "geopolitics" for k in ("sL", "sC", "sR", "sC2")}
    bias = {"sL": "Left", "sC": "Center", "sR": "Right", "sC2": "Lean Center"}
    keep, drops = td.select_representatives(members, bias, cat, GEO)
    ok("bias_keep_set", set(keep) == {"a", "c", "d"})         # early=a, dev=c, left=a, center=d, right=c
    ok("bias_drop_b", [x["id"] for x in drops] == ["b"])      # b is a worse center than d


def test_bias_skipped_for_non_bias_category():
    members = [m("a", "2026-06-15T01:00:00+00:00", "sL"),
               m("b", "2026-06-15T05:00:00+00:00", "sR"),
               m("c", "2026-06-15T09:00:00+00:00", "sC")]
    cat = {"sL": "tech", "sR": "tech", "sC": "tech"}
    bias = {"sL": "Left", "sR": "Right", "sC": "Center"}
    keep, drops = td.select_representatives(members, bias, cat, GEO)
    ok("tech_no_bias_split", set(keep) == {"a", "c"})         # temporal only despite bias tags
    ok("tech_drop_mid", [d["id"] for d in drops] == ["b"])


def test_bias_missing_side_not_forced():
    members = [m("a", "2026-06-15T01:00:00+00:00", "sL"),     # left
               m("b", "2026-06-15T09:00:00+00:00", "sC")]     # center, no right
    cat = {"sL": "pakistan", "sC": "pakistan"}
    bias = {"sL": "Left", "sC": "Center"}
    keep, drops = td.select_representatives(members, bias, cat, GEO)
    ok("missing_side", set(keep) == {"a", "b"} and drops == [])   # both kept, no right invented


def test_bias_unseeded_degrades_to_temporal():
    members = [m("a", "2026-06-15T01:00:00+00:00", "s1"),
               m("b", "2026-06-15T05:00:00+00:00", "s2"),
               m("c", "2026-06-15T09:00:00+00:00", "s3")]
    cat = {"s1": "geopolitics", "s2": "geopolitics", "s3": "geopolitics"}
    keep, _ = td.select_representatives(members, {}, cat, GEO)   # bias_of empty -> unseeded
    ok("unseeded_temporal", set(keep) == {"a", "c"})


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
