"""
Tests for deliver_brief.wait_for_brief — the safety-net that waits for today's fresh
brief instead of giving up the instant it is missing (no-delivery incident, 2026-06-14).

Pure logic: wait_for_brief(load_fn, max_wait_s, poll_s, sleep_fn, time_fn) calls
load_fn() until it returns a truthy brief or max_wait_s elapses, sleeping poll_s
between tries. Injected sleep_fn/time_fn keep it deterministic and instant.

    venv\\Scripts\\python.exe tests\\test_deliver_wait.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import deliver_brief as db  # noqa: E402

PASS = []


def ok(name, cond):
    if not cond:
        raise AssertionError(name)
    PASS.append(name)


class Clock:
    """Fake monotonic clock; sleep advances it (no real waiting)."""
    def __init__(self):
        self.t = 0.0
        self.sleeps = []

    def time(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


def loader(results):
    """load_fn returning each queued (brief, reason) once, then repeating the last."""
    state = {"i": 0, "calls": 0}

    def fn():
        state["calls"] += 1
        i = min(state["i"], len(results) - 1)
        state["i"] += 1
        return results[i]
    fn.calls = lambda: state["calls"]
    return fn


def test_returns_immediately_when_brief_present_no_sleep():
    clk = Clock()
    load = loader([({"id": "real"}, None)])
    brief, why = db.wait_for_brief(load, 240, 15, clk.sleep, clk.time)
    ok("imm_brief", brief is not None and brief["id"] == "real")
    ok("imm_reason_none", why is None)
    ok("imm_no_sleep", clk.sleeps == [])
    ok("imm_one_load", load.calls() == 1)


def test_waits_then_succeeds():
    clk = Clock()
    load = loader([(None, "no fresh non-empty brief"),
                   (None, "no fresh non-empty brief"),
                   ({"id": "real"}, None)])
    brief, why = db.wait_for_brief(load, 240, 15, clk.sleep, clk.time)
    ok("wait_brief", brief is not None and brief["id"] == "real")
    ok("wait_two_sleeps", clk.sleeps == [15, 15])
    ok("wait_three_loads", load.calls() == 3)


def test_times_out_and_returns_reason_bounded():
    clk = Clock()
    load = loader([(None, "no fresh non-empty brief")])  # never succeeds
    brief, why = db.wait_for_brief(load, 30, 15, clk.sleep, clk.time)
    ok("to_none", brief is None)
    ok("to_reason", why == "no fresh non-empty brief")
    # budget 30, poll 15: load@0, sleep->15, load@15, sleep->30, load@30 (>=30 stop).
    ok("to_bounded_sleeps", clk.sleeps == [15, 15])
    ok("to_three_loads", load.calls() == 3)


def test_zero_wait_reproduces_no_wait():
    clk = Clock()
    load = loader([(None, "no fresh non-empty brief")])
    brief, why = db.wait_for_brief(load, 0, 15, clk.sleep, clk.time)
    ok("zero_none", brief is None and why is not None)
    ok("zero_no_sleep", clk.sleeps == [])
    ok("zero_one_load", load.calls() == 1)


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
