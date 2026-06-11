"""
Tests for agents/run_log.py — best-effort agent_runs writer.

Contract (#5 from the 2026-06-11 audit): a bookkeeping insert that fails must
NOT raise. The final agent_runs insert sits after all real work; if it threw,
the agent would exit non-zero and a *successfully built* brief could be blocked
from delivery. record_run() logs and swallows instead.

    venv\\Scripts\\python.exe tests\\test_run_log.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
import run_log  # noqa: E402


class _Exec:
    def __init__(self, fail):
        self.fail = fail

    def execute(self):
        if self.fail:
            raise RuntimeError("db down")
        return {"data": [{"id": 1}]}


class _Table:
    def __init__(self, captured, fail):
        self.captured = captured
        self.fail = fail

    def insert(self, payload):
        self.captured.append(payload)
        return _Exec(self.fail)


class FakeSB:
    def __init__(self, fail=False):
        self.fail = fail
        self.captured = []
        self.table_name = None

    def table(self, name):
        self.table_name = name
        return _Table(self.captured, self.fail)


def test_healthy_insert_passes_payload_through():
    sb = FakeSB(fail=False)
    payload = {"agent_name": "classifier", "status": "success"}
    ok = run_log.record_run(sb, payload)
    assert ok is True, "should report success"
    assert sb.table_name == "agent_runs", "must write to agent_runs"
    assert sb.captured == [payload], "payload must reach the DB unchanged"
    print("PASS: healthy_insert_passes_payload_through")


def test_failing_insert_is_swallowed_not_raised():
    sb = FakeSB(fail=True)
    payload = {"agent_name": "writer", "status": "success"}
    # The whole point: this must NOT raise even though execute() throws.
    ok = run_log.record_run(sb, payload)
    assert ok is False, "should report failure"
    print("PASS: failing_insert_is_swallowed_not_raised")


def main():
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
            except Exception as e:
                print(f"FAIL: {name}: {type(e).__name__}: {e}")
                failed += 1
    print(f"\n{'all passed' if not failed else str(failed) + ' failed'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
