"""
Tests for agents/deliver.py — the §4.3 confirmed-delivery seam.

The invariant: a brief's article IDs are recorded as delivered ONLY after EVERY
chunk/message of that send returns a real messageId. If any send fails, record
NOTHING and fire an alert. No duplicate recording (idempotent recorder).

Pure logic, no real send / DB / Telegram (everything injected).

    venv\\Scripts\\python.exe tests\\test_deliver.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
import deliver as d  # noqa: E402

PASS = []


def ok(name, cond):
    if not cond:
        raise AssertionError(name)
    PASS.append(name)


class Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, account, article_ids, brief_id=None):
        self.calls.append((account, list(article_ids), brief_id))
        return len(article_ids)


class Alerter:
    def __init__(self):
        self.calls = []

    def __call__(self, text):
        self.calls.append(text)
        return True


def good_send(_chunk, _i=[0]):
    _i[0] += 1
    return f"mid{_i[0]}"


def fail_on_2nd():
    state = {"n": 0}

    def send(_chunk):
        state["n"] += 1
        return None if state["n"] == 2 else f"mid{state['n']}"
    return send


# --- deliver_confirmed -----------------------------------------------------
def test_confirmed_all_ok():
    okall, ids = d.deliver_confirmed(["a", "b", "c"], lambda c: "x")
    ok("confirmed_all_ok", okall is True and len(ids) == 3)


def test_confirmed_stops_at_failure():
    okall, ids = d.deliver_confirmed(["a", "b", "c"], fail_on_2nd())
    ok("confirmed_partial", okall is False and len(ids) == 1)


# --- deliver_and_record (THE seam) -----------------------------------------
def test_success_records_once_no_alert():
    rec, alert = Recorder(), Alerter()
    res = d.deliver_and_record(
        ["a1", "a2"], ["chunk1", "chunk2"], "newsframer", "brief-1",
        send_fn=lambda c: "mid", record_fn=rec, alert_fn=alert,
    )
    ok("succ_ok", res["ok"] is True)
    ok("succ_recorded_once", len(rec.calls) == 1)
    ok("succ_recorded_ids", rec.calls[0] == ("newsframer", ["a1", "a2"], "brief-1"))
    ok("succ_no_alert", len(alert.calls) == 0)
    ok("succ_count", res["recorded"] == 2)


def test_failed_send_records_nothing_and_alerts():
    rec, alert = Recorder(), Alerter()
    res = d.deliver_and_record(
        ["a1", "a2"], ["chunk1", "chunk2", "chunk3"], "newsframer", "brief-1",
        send_fn=fail_on_2nd(), record_fn=rec, alert_fn=alert,
    )
    ok("fail_not_ok", res["ok"] is False)
    ok("fail_no_record", len(rec.calls) == 0)         # <-- recorded NOTHING
    ok("fail_recorded_zero", res["recorded"] == 0)
    ok("fail_alert_fired", len(alert.calls) == 1)     # <-- alert fired


def test_no_duplicate_recording_on_repeat_calls():
    # Two runs (e.g. a retry) must not double-record: the recorder is idempotent
    # by (article_id, account); the seam calls it once per successful run.
    rec, alert = Recorder(), Alerter()
    for _ in range(2):
        d.deliver_and_record(["a1"], ["c1"], "acct", None,
                             send_fn=lambda c: "mid", record_fn=rec, alert_fn=alert)
    ok("repeat_two_calls", len(rec.calls) == 2)        # one per run...
    ok("repeat_same_ids", all(c[1] == ["a1"] for c in rec.calls))  # ...same ids (DB upsert dedupes)


# --- split_for_telegram ----------------------------------------------------
def test_split_short_single_chunk():
    chunks = d.split_for_telegram("# Brief\n\n## A\nshort body", limit=4000)
    ok("split_short_one", len(chunks) == 1)


def test_split_at_section_boundaries():
    big = "## A\n" + ("x" * 1500) + "\n## B\n" + ("y" * 1500) + "\n## C\n" + ("z" * 1500)
    chunks = d.split_for_telegram(big, limit=2000)
    ok("split_multi", len(chunks) >= 2)
    ok("split_under_limit", all(len(c) <= 2000 for c in chunks))


def test_split_oversized_section_hard_split():
    huge = "## A\n" + ("x" * 9000)
    chunks = d.split_for_telegram(huge, limit=2000)
    ok("split_hard_under_limit", all(len(c) <= 2000 for c in chunks))
    ok("split_hard_preserves", "".join(chunks).count("x") == 9000)


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
