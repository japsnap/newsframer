"""
Tests for gateway_watchdog.decide — the pure branch that drives the independent gateway watchdog.
(The IO wrappers ping/restart/alert are thin and exercised by the live --dry-run smoke.)

    venv\\Scripts\\python.exe tests\\test_gateway_watchdog.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import gateway_watchdog as gw  # noqa: E402

PASS = []


def ok(name, cond):
    if not cond:
        raise AssertionError(name)
    PASS.append(name)


def test_decide():
    ok("reachable_is_ok", gw.decide(True) == "ok")               # gateway up -> nothing
    ok("unreachable_is_restart", gw.decide(False) == "restart")  # gateway down -> heal + alert
    ok("unknown_is_skip", gw.decide(None) == "skip")             # CLI missing -> never act blindly


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
