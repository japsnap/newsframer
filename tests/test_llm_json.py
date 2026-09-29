"""
Tests for agents/llm_json.py — robust extraction of JSON from LLM responses.

These pin down the failure class behind the 2026-06-11 classifier incident:
Gemini/Haiku drift on output SHAPE (object vs array vs string vs null, with or
without markdown fences / surrounding prose). The pipeline must degrade to
"skip this item", never crash with 'str'/'list' object has no attribute 'get'.

No pytest in this venv -> plain asserts, runnable directly:
    venv\\Scripts\\python.exe tests\\test_llm_json.py
Exits 0 if all pass, 1 on first failure.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
import llm_json  # noqa: E402


CASES_PASSED = []


def check(name, cond):
    if not cond:
        print(f"FAIL: {name}")
        raise AssertionError(name)
    CASES_PASSED.append(name)


# ---------------------------------------------------------------------------
# parse_json_list  (classifier: ALWAYS returns a list of dicts, never crashes)
# ---------------------------------------------------------------------------
def test_list_passthrough():
    out = llm_json.parse_json_list('[{"article_id": "a"}, {"article_id": "b"}]')
    check("list_passthrough", out == [{"article_id": "a"}, {"article_id": "b"}])


def test_single_object_wrapped():
    # The EXACT 2026-06-11 bug: one-article batch -> bare object, not array.
    out = llm_json.parse_json_list('{"article_id": "a", "branch": "IMMEDIATE"}')
    check("single_object_wrapped", out == [{"article_id": "a", "branch": "IMMEDIATE"}])


def test_fenced_array():
    out = llm_json.parse_json_list('```json\n[{"article_id": "a"}]\n```')
    check("fenced_array", out == [{"article_id": "a"}])


def test_fenced_single_object():
    out = llm_json.parse_json_list('```\n{"article_id": "a"}\n```')
    check("fenced_single_object", out == [{"article_id": "a"}])


def test_leading_prose():
    out = llm_json.parse_json_list('Here is the JSON:\n[{"article_id": "a"}]')
    check("leading_prose", out == [{"article_id": "a"}])


def test_trailing_prose():
    out = llm_json.parse_json_list('[{"article_id": "a"}]\nDone.')
    check("trailing_prose", out == [{"article_id": "a"}])


def test_prose_around_fence():
    out = llm_json.parse_json_list('Sure:\n```json\n[{"article_id": "a"}]\n```\nThanks!')
    check("prose_around_fence", out == [{"article_id": "a"}])


def test_bare_null_returns_empty():
    # json 'null' -> None. Must NOT crash on iteration; treated as no results.
    check("bare_null_returns_empty", llm_json.parse_json_list("null") == [])


def test_json_string_returns_empty():
    # A quoted sentence is valid JSON (a str). Old code iterated its chars.
    check("json_string_returns_empty", llm_json.parse_json_list('"no articles to classify"') == [])


def test_list_with_nondict_filtered():
    out = llm_json.parse_json_list('[{"article_id": "a"}, "junk", null, 5]')
    check("list_with_nondict_filtered", out == [{"article_id": "a"}])


def test_empty_array():
    check("empty_array", llm_json.parse_json_list("[]") == [])


def test_list_result_is_all_dicts():
    # Property the caller relies on: every element supports .get(...)
    out = llm_json.parse_json_list('[{"a": 1}, "x", {"b": 2}]')
    check("list_result_is_all_dicts", all(isinstance(r, dict) for r in out))


# ---------------------------------------------------------------------------
# parse_json_obj  (analyst: ALWAYS returns one dict, or raises for retry)
# ---------------------------------------------------------------------------
def test_obj_passthrough():
    out = llm_json.parse_json_obj('{"relevance_score": 7}')
    check("obj_passthrough", out == {"relevance_score": 7})


def test_array_unwrapped_to_obj():
    # The MIRROR bug: analyst asked for one object, got a 1-item array.
    out = llm_json.parse_json_obj('[{"relevance_score": 7}]')
    check("array_unwrapped_to_obj", out == {"relevance_score": 7})


def test_obj_fenced():
    out = llm_json.parse_json_obj('```json\n{"relevance_score": 7}\n```')
    check("obj_fenced", out == {"relevance_score": 7})


def test_obj_prose():
    out = llm_json.parse_json_obj('Result:\n{"relevance_score": 7}\n-- end')
    check("obj_prose", out == {"relevance_score": 7})


def test_array_multi_takes_first_dict():
    out = llm_json.parse_json_obj('[{"relevance_score": 7}, {"relevance_score": 2}]')
    check("array_multi_takes_first_dict", out == {"relevance_score": 7})


def _raises(fn, *a):
    try:
        fn(*a)
        return False
    except Exception:
        return True


def test_obj_bare_string_raises():
    check("obj_bare_string_raises", _raises(llm_json.parse_json_obj, '"nope"'))


def test_obj_null_raises():
    check("obj_null_raises", _raises(llm_json.parse_json_obj, "null"))


def test_obj_empty_array_raises():
    check("obj_empty_array_raises", _raises(llm_json.parse_json_obj, "[]"))


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError:
            failed += 1
        except Exception as e:
            print(f"ERROR in {t.__name__}: {type(e).__name__}: {e}")
            failed += 1
    print(f"\n{len(CASES_PASSED)} checks passed, {failed} test(s) failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
