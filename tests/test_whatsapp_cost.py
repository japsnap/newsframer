"""
Tests for the WhatsApp-path cost logging (NF-14): _usage_tokens + _record_llm_cost.
The WhatsApp brief generation + Urdu translation (group + Friend DM) were previously UNTRACKED;
they now log to agent_runs + execution_log via record_run so the cost is no longer invisible.
Pure (no network / no LLM).

    venv\\Scripts\\python.exe tests\\test_whatsapp_cost.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import run_whatsapp_brief as w  # noqa: E402

PASS = []


def ok(name, cond):
    if not cond:
        raise AssertionError(name)
    PASS.append(name)


class _Usage:
    def __init__(self, i, o):
        self.prompt_tokens = i
        self.completion_tokens = o


class _Resp:
    def __init__(self, i, o):
        self.usage = _Usage(i, o)


class _NoUsage:
    usage = None


class _Exec:
    def execute(self):
        return {"data": [{"id": 1}]}


class _Table:
    def __init__(self, name, log):
        self.name = name
        self.log = log

    def insert(self, payload):
        self.log.append((self.name, payload))
        return _Exec()


class FakeSB:
    def __init__(self):
        self.inserts = []

    def table(self, name):
        return _Table(name, self.inserts)


def _agent_rows(sb):
    return [p for (t, p) in sb.inserts if t == "agent_runs"]


def test_usage_tokens():
    ok("tokens", w._usage_tokens(_Resp(100, 50)) == (100, 50))
    ok("no_usage_attr", w._usage_tokens(_NoUsage()) == (0, 0))
    ok("none_resp", w._usage_tokens(None) == (0, 0))


def test_record_llm_cost_logs_a_row():
    sb = FakeSB()
    cost = w._record_llm_cost(sb, {}, "whatsapp_writer", "anthropic/claude-haiku-4-5", _Resp(100, 50))
    ok("cost_is_number", isinstance(cost, (int, float)) and cost >= 0)
    ar = _agent_rows(sb)
    ok("one_row", len(ar) == 1)
    ok("agent_name", ar[0]["agent_name"] == "whatsapp_writer")
    ok("tokens_logged", ar[0]["tokens_in"] == 100 and ar[0]["tokens_out"] == 50)
    ok("model_logged", ar[0]["model_used"] == "anthropic/claude-haiku-4-5")
    ok("status_success", ar[0]["status"] == "success")


def test_record_translate_label():
    sb = FakeSB()
    w._record_llm_cost(sb, {}, "whatsapp_translate", "m", _Resp(0, 0))
    ok("translate_agent", _agent_rows(sb)[0]["agent_name"] == "whatsapp_translate")


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
