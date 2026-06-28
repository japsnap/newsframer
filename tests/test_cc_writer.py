"""
Tests for the writer-on-subscription parse seam (agents/cc_writer.parse_cc_json) — pure, no subprocess.

    venv\\Scripts\\python.exe tests\\test_cc_writer.py
"""
import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
import cc_writer as cw  # noqa: E402

PASS = []


def ok(name, cond):
    if not cond:
        raise AssertionError(name)
    PASS.append(name)


def test_parse_success():
    payload = json.dumps({
        "type": "result", "subtype": "success", "is_error": False,
        "result": "# NewsFramer Briefing\n\n## Geopolitics\n...",
        "usage": {"input_tokens": 100, "cache_creation_input_tokens": 24000,
                  "cache_read_input_tokens": 500, "output_tokens": 1500},
        "modelUsage": {"claude-sonnet-4-6": {"inputTokens": 100}},
    })
    text, model, t_in, t_out = cw.parse_cc_json(payload)
    ok("text_kept", text.startswith("# NewsFramer Briefing"))
    ok("model_labeled", model == "subscription:claude-sonnet-4-6")
    ok("tokens_in_summed", t_in == 24600)   # 100 + 24000 + 500
    ok("tokens_out", t_out == 1500)


def test_parse_no_modelusage_defaults_label():
    payload = json.dumps({"subtype": "success", "result": "hi", "usage": {"output_tokens": 2}})
    _t, model, _i, t_out = cw.parse_cc_json(payload)
    ok("default_label", model == "subscription:claude-code")
    ok("out_only", t_out == 2)


def test_parse_errors_raise():
    def raises(payload):
        try:
            cw.parse_cc_json(payload)
            return False
        except Exception:
            return True
    ok("is_error_raises", raises(json.dumps({"is_error": True, "subtype": "success", "result": "x"})))
    ok("non_success_raises", raises(json.dumps({"subtype": "error_max_turns", "result": "x"})))
    ok("empty_result_raises", raises(json.dumps({"subtype": "success", "result": "   "})))
    ok("bad_json_raises", raises("not json at all"))


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
