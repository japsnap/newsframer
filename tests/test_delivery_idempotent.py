"""
Tests for idempotent delivery (the retry-redelivery fix): the local delivered-marker and the
already_delivered DB check. The §4.3 invariant is the load-bearing one — the marker is written ONLY
after a fully confirmed send, never on a partial/failed send.

    venv\\Scripts\\python.exe tests\\test_delivery_idempotent.py
"""
import os
import sys
import shutil
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import deliver as dlv          # noqa: E402
import deliver_brief as db     # noqa: E402

PASS = []


def ok(name, cond):
    if not cond:
        raise AssertionError(name)
    PASS.append(name)


def test_local_marker_roundtrip():
    base = tempfile.mkdtemp()
    try:
        ok("absent_before", dlv.is_delivered_local(base, "brief-1", "newsframer") is False)
        dlv.mark_delivered_local(base, "brief-1", "newsframer", now=123.0)
        ok("present_after", dlv.is_delivered_local(base, "brief-1", "newsframer") is True)
        ok("other_brief_absent", dlv.is_delivered_local(base, "brief-2", "newsframer") is False)
        ok("other_account_absent", dlv.is_delivered_local(base, "brief-1", "whatsapp:happy") is False)
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_marker_only_after_confirmed_send():
    """Wrap record_fn to write the marker — exactly how deliver_brief does it — and prove the §4.3
    invariant: a FAILED send never writes the marker; a fully-confirmed send does."""
    base = tempfile.mkdtemp()
    try:
        def record_fn(account, article_ids, brief_id):
            dlv.mark_delivered_local(base, brief_id, account)
            return len(article_ids)

        # all chunks confirm -> marker written
        res = dlv.deliver_and_record(["a1", "a2"], ["c1", "c2"], "newsframer", "brief-OK",
                                     send_fn=lambda c: "mid-" + c, record_fn=record_fn,
                                     alert_fn=lambda t: None, label="t")
        ok("ok_true", res["ok"] is True)
        ok("marker_on_success", dlv.is_delivered_local(base, "brief-OK", "newsframer") is True)

        # second chunk fails -> record_fn never runs -> NO marker (no false 'delivered')
        res2 = dlv.deliver_and_record(["a1"], ["c1", "c2"], "newsframer", "brief-FAIL",
                                      send_fn=lambda c: None if c == "c2" else "mid",
                                      record_fn=record_fn, alert_fn=lambda t: None, label="t")
        ok("fail_false", res2["ok"] is False)
        ok("no_marker_on_fail", dlv.is_delivered_local(base, "brief-FAIL", "newsframer") is False)
    finally:
        shutil.rmtree(base, ignore_errors=True)


# --- already_delivered (DB check) against a fake Supabase -------------------
class _FakeQ:
    def __init__(self, data):
        self._data = data

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        class _R:
            pass
        r = _R()
        r.data = self._data
        return r


class _FakeSB:
    def __init__(self, data):
        self._data = data

    def table(self, _name):
        return _FakeQ(self._data)


def test_already_delivered():
    ok("delivered_true", db.already_delivered(_FakeSB([{"article_id": "x"}]), "b1", "newsframer") is True)
    ok("delivered_false", db.already_delivered(_FakeSB([]), "b1", "newsframer") is False)


def test_already_delivered_fails_open():
    class _Boom:
        def table(self, _n):
            raise RuntimeError("db down")
    # a check error must NOT suppress delivery -> returns False (fail open)
    ok("fail_open", db.already_delivered(_Boom(), "b1", "newsframer") is False)


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
