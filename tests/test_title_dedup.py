"""
Tests for agents/title_dedup.py (NF-NEW10) — the pure logic only (no DB, no LLM):
keeper selection, the confirm prompt, tolerant yes/no parsing, and the injected-LLM
confirm path (incl. error -> keep all). No network.

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


def m(id_, pub, title="t"):
    return {"id": id_, "published_at": pub, "title": title, "cluster_id": "c"}


# --- select_drops: keep the EARLIEST (originator), drop the rest ------------
def test_select_drops_keeps_earliest():
    members = [m("b", "2026-06-15T06:00:00+00:00"),
               m("a", "2026-06-15T01:00:00+00:00"),
               m("c", "2026-06-15T09:00:00+00:00")]
    keeper, drops = td.select_drops(members)
    ok("keeper_earliest", keeper["id"] == "a")
    ok("drops_count", len(drops) == 2)
    ok("drops_are_later", {d["id"] for d in drops} == {"b", "c"})


def test_select_drops_singleton_and_empty():
    one, d1 = td.select_drops([m("x", "2026-06-15T00:00:00+00:00")])
    ok("single_keeper", one["id"] == "x" and d1 == [])
    none, d0 = td.select_drops([])
    ok("empty_safe", none is None and d0 == [])


def test_select_drops_tie_breaks_by_id():
    members = [m("z", "2026-06-15T00:00:00+00:00"), m("a", "2026-06-15T00:00:00+00:00")]
    keeper, drops = td.select_drops(members)
    ok("tie_stable", keeper["id"] == "a" and drops[0]["id"] == "z")


# --- build_confirm_prompt --------------------------------------------------
def test_build_confirm_prompt():
    p = td.build_confirm_prompt(["Iran deal signed", "US and Iran reach pact"])
    ok("lists_titles", "Iran deal signed" in p and "US and Iran reach pact" in p)
    ok("asks_same_event", "same_event" in p and "SAME" in p)


# --- parse_confirm: True only on explicit same_event:true ------------------
def test_parse_confirm():
    ok("true", td.parse_confirm('{"same_event": true}') is True)
    ok("false", td.parse_confirm('{"same_event": false}') is False)
    ok("yes_str", td.parse_confirm('{"same_event": "yes"}') is True)
    ok("no_str", td.parse_confirm('{"same_event": "no"}') is False)
    ok("fenced", td.parse_confirm('```json\n{"same_event": true}\n```') is True)
    ok("prose_wrapped", td.parse_confirm('Sure: {"same_event": true} done') is True)
    ok("garbage_false", td.parse_confirm("not json at all") is False)
    ok("empty_obj_false", td.parse_confirm("{}") is False)
    ok("missing_false", td.parse_confirm('{"other": true}') is False)
    ok("int_is_conservative", td.parse_confirm('{"same_event": 1}') is False)  # ambiguous -> keep all


# --- confirm_same_event: injected LLM, error -> keep all -------------------
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


def test_confirm_same_event_error_keeps_all():
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
