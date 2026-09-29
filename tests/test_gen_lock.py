"""
Tests for the single-generation lock (agents/gen_lock.py) — the double-generation fix.
Pure, runs against a tempdir with injected now/pid (no real time, no real run).

    venv\\Scripts\\python.exe tests\\test_gen_lock.py
"""
import os
import sys
import shutil
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
import gen_lock  # noqa: E402

PASS = []


def ok(name, cond):
    if not cond:
        raise AssertionError(name)
    PASS.append(name)


def test_second_concurrent_acquire_noops():
    d = tempfile.mkdtemp()
    try:
        a1, _ = gen_lock.acquire("run_brief", "brief-2026-06-26", d, 3600, now=1000.0, pid=111)
        a2, holder = gen_lock.acquire("run_brief", "brief-2026-06-26", d, 3600, now=1010.0, pid=222)
        ok("first_acquires", a1 is True)
        ok("second_noops", a2 is False)            # the cron-retry no-ops instead of re-running
        ok("holder_is_first_run", holder.get("pid") == 111)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_stale_lock_reclaimed():
    d = tempfile.mkdtemp()
    try:
        gen_lock.acquire("run_brief", "brief-x", d, 3600, now=1000.0, pid=111)
        # 2h later (> stale 3600s): a crashed run's lock is reclaimed so the next run isn't blocked
        a2, holder = gen_lock.acquire("run_brief", "brief-x", d, 3600, now=1000.0 + 7200, pid=222)
        ok("stale_reclaimed", a2 is True and holder.get("pid") == 222)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_live_long_run_not_reclaimed():
    d = tempfile.mkdtemp()
    try:
        gen_lock.acquire("run_brief", "k", d, 3600, now=1000.0, pid=111)
        # 38 min later (< stale 3600s): a still-running long build keeps its lock (retry no-ops)
        a2, _ = gen_lock.acquire("run_brief", "k", d, 3600, now=1000.0 + 38 * 60, pid=222)
        ok("live_run_keeps_lock", a2 is False)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_different_key_is_free():
    d = tempfile.mkdtemp()
    try:
        gen_lock.acquire("run_brief", "brief-day1", d, 3600, now=1000.0)
        a2, _ = gen_lock.acquire("run_brief", "brief-day2", d, 3600, now=1010.0)  # next day -> free
        ok("new_day_acquires", a2 is True)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_release_allows_reacquire():
    d = tempfile.mkdtemp()
    try:
        gen_lock.acquire("run_brief", "k", d, 3600, now=1000.0)
        gen_lock.release("run_brief", "k", d)
        a2, _ = gen_lock.acquire("run_brief", "k", d, 3600, now=1010.0)
        ok("reacquire_after_release", a2 is True)
    finally:
        shutil.rmtree(d, ignore_errors=True)


def test_release_only_own_key():
    d = tempfile.mkdtemp()
    try:
        gen_lock.acquire("run_brief", "kA", d, 3600, now=1000.0)
        gen_lock.release("run_brief", "kB", d)   # foreign key -> must NOT delete kA
        a2, _ = gen_lock.acquire("run_brief", "kA", d, 3600, now=1010.0)
        ok("foreign_release_is_noop", a2 is False)
    finally:
        shutil.rmtree(d, ignore_errors=True)


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
