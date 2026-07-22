"""
Tests for agents/run_log.py — best-effort agent_runs writer + the NF-14 execution_log mirror.

Contract (#5 from the 2026-06-11 audit): a bookkeeping insert that fails must NOT raise. The
final agent_runs insert sits after all real work; if it threw, the agent would exit non-zero and
a *successfully built* brief could be blocked from delivery. record_run() logs and swallows. The
execution_log mirror (NF-14) is held to the same contract: isolated, best-effort, never raises.

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
    def __init__(self, name, log, fail):
        self.name = name
        self.log = log
        self.fail = fail

    def insert(self, payload):
        self.log.append((self.name, payload))
        return _Exec(self.fail)


class FakeSB:
    """Captures every insert as (table_name, payload)."""
    def __init__(self, fail=False):
        self.fail = fail
        self.inserts = []

    def table(self, name):
        return _Table(name, self.inserts, self.fail)


def _rows(sb, table):
    return [p for (t, p) in sb.inserts if t == table]


def test_healthy_insert_writes_agent_runs_payload():
    sb = FakeSB(fail=False)
    payload = {"agent_name": "classifier", "status": "success", "cost_usd": 0.01}
    ok = run_log.record_run(sb, payload)
    assert ok is True, "should report success"
    ar = _rows(sb, "agent_runs")
    assert ar and ar[0] == payload, "agent_runs must get the payload unchanged"
    print("PASS: healthy_insert_writes_agent_runs_payload")


def test_failing_agent_runs_insert_is_swallowed():
    sb = FakeSB(fail=True)  # both the agent_runs AND the mirror insert raise
    ok = run_log.record_run(sb, {"agent_name": "writer", "status": "success"})
    assert ok is False, "should report failure, not raise"
    print("PASS: failing_agent_runs_insert_is_swallowed")


def test_build_exec_row_maps_fields():
    row = run_log.build_exec_row(
        {"agent_name": "analyst", "model_used": "m", "cost_usd": 0.5, "tokens_in": 10,
         "tokens_out": 20, "status": "success", "error": None,
         "linked_hypotheses": ["h1"], "artifact_verified": True},
        "trace-x", "brief")
    assert row["trace_id"] == "trace-x" and row["task_type"] == "brief" and row["project"] == "newsframer"
    assert row["agent"] == "analyst" and row["model_used"] == "m"
    assert row["actual_cost"] == 0.5 and row["tokens_in"] == 10 and row["tokens_out"] == 20
    assert row["status"] == "success" and row["error_trace"] is None
    assert row["linked_hypotheses"] == ["h1"] and row["artifact_verified"] is True
    print("PASS: build_exec_row_maps_fields")


def test_build_exec_row_defaults():
    row = run_log.build_exec_row({"agent_name": "fetcher"}, "t", "brief")
    assert row["actual_cost"] == 0 and row["tokens_in"] == 0 and row["tokens_out"] == 0
    assert row["artifact_verified"] is False and row["linked_hypotheses"] is None
    print("PASS: build_exec_row_defaults")


def test_exec_only_fields_stripped_from_agent_runs():
    """agent_runs has NO artifact_verified / linked_hypotheses columns — those are execution_log
    fields that ride through the payload. Passing them into the agent_runs insert made it fail
    SILENTLY on every writer run from 2026-06-18 to 2026-07-22 (the swallow hid a month of missing
    writer rows). They must be stripped from the agent_runs row yet still reach execution_log."""
    sb = FakeSB(fail=False)
    os.environ.pop("NEWSFRAMER_TRACE_ID", None)
    ok = run_log.record_run(sb, {"agent_name": "writer", "status": "success",
                                 "artifact_verified": True, "linked_hypotheses": ["h1"]})
    ar = _rows(sb, "agent_runs")
    ex = _rows(sb, "execution_log")
    assert ok is True
    assert ar and "artifact_verified" not in ar[0] and "linked_hypotheses" not in ar[0]
    assert ar[0]["agent_name"] == "writer" and ar[0]["status"] == "success"
    assert ex and ex[0]["artifact_verified"] is True and ex[0]["linked_hypotheses"] == ["h1"]
    print("PASS: exec_only_fields_stripped_from_agent_runs")


def test_mirror_writes_execution_log_with_trace():
    sb = FakeSB(fail=False)
    inserted = run_log.mirror_execution_log(
        sb, {"agent_name": "writer", "status": "success"},
        trace_id="t1", task_type="brief", enabled=True)
    assert inserted is True
    ex = _rows(sb, "execution_log")
    assert ex and ex[0]["trace_id"] == "t1" and ex[0]["agent"] == "writer"
    print("PASS: mirror_writes_execution_log_with_trace")


def test_mirror_disabled_writes_nothing():
    sb = FakeSB(fail=False)
    inserted = run_log.mirror_execution_log(sb, {"agent_name": "x"}, trace_id="t", enabled=False)
    assert inserted is False and _rows(sb, "execution_log") == []
    print("PASS: mirror_disabled_writes_nothing")


def test_mirror_trace_from_env(monkeypatch=None):
    sb = FakeSB(fail=False)
    os.environ["NEWSFRAMER_TRACE_ID"] = "env-trace"
    os.environ["NEWSFRAMER_TASK_TYPE"] = "brief"
    try:
        run_log.mirror_execution_log(sb, {"agent_name": "fetcher"}, enabled=True)
        ex = _rows(sb, "execution_log")
        assert ex and ex[0]["trace_id"] == "env-trace"
    finally:
        del os.environ["NEWSFRAMER_TRACE_ID"]
        del os.environ["NEWSFRAMER_TASK_TYPE"]
    print("PASS: mirror_trace_from_env")


def test_mirror_solo_trace_when_no_env():
    sb = FakeSB(fail=False)
    os.environ.pop("NEWSFRAMER_TRACE_ID", None)
    run_log.mirror_execution_log(sb, {"agent_name": "dedup"}, enabled=True)
    ex = _rows(sb, "execution_log")
    assert ex and ex[0]["trace_id"] == "solo-dedup"
    print("PASS: mirror_solo_trace_when_no_env")


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
