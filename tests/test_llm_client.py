"""
Tests for agents/llm_client.py — hard timeout + provider fallback + sticky breaker
(2026-06-22 Gemini-outage resilience). No network: a fake completion_fn drives ok/raise/hang.

    venv\\Scripts\\python.exe tests\\test_llm_client.py
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
import llm_client as lc  # noqa: E402

PASS = []


def ok(name, cond):
    if not cond:
        raise AssertionError(name)
    PASS.append(name)


class FakeLLM:
    """Records call order; per-model behaviour 'ok' | 'raise' | 'hang'."""
    def __init__(self, behavior=None):
        self.calls = []
        self.behavior = behavior or {}

    def __call__(self, model=None, messages=None, **kw):
        self.calls.append(model)
        b = self.behavior.get(model, "ok")
        if b == "raise":
            raise RuntimeError(f"{model} boom")
        if b == "hang":
            time.sleep(2.0)            # longer than the test timeout -> LLMTimeout
        return {"model": model, "content": "OK"}


# ---- call_bounded ----
def test_call_bounded_fast_returns():
    ok("bounded_value", lc.call_bounded(lambda: 42, 1.0) == 42)


def test_call_bounded_times_out():
    try:
        lc.call_bounded(lambda: time.sleep(1.0), 0.2)
        ok("bounded_timeout", False)
    except lc.LLMTimeout:
        ok("bounded_timeout", True)


def test_call_bounded_propagates_error():
    def boom():
        raise ValueError("x")
    try:
        lc.call_bounded(boom, 1.0)
        ok("bounded_propagate", False)
    except ValueError:
        ok("bounded_propagate", True)


# ---- ResilientLLM ----
def test_healthy_run_uses_primary_only():
    fake = FakeLLM()
    r = lc.ResilientLLM("P", fallback="F", timeout_s=1.0, completion_fn=fake)
    resp, used = r.complete([{"role": "user", "content": "hi"}])
    ok("healthy_used_primary", used == "P")
    ok("healthy_no_fallback_flag", r.used_fallback is False)
    ok("healthy_breaker_closed", r.breaker_open is False)
    ok("healthy_only_primary_called", fake.calls == ["P"])


def test_primary_raises_falls_back():
    fake = FakeLLM({"P": "raise"})
    r = lc.ResilientLLM("P", fallback="F", timeout_s=1.0, completion_fn=fake)
    resp, used = r.complete([])
    ok("fb_used_fallback", used == "F" and r.used_fallback is True)
    ok("fb_call_order", fake.calls == ["P", "F"])


def test_primary_hangs_falls_back_fast():
    fake = FakeLLM({"P": "hang"})
    r = lc.ResilientLLM("P", fallback="F", timeout_s=0.3, completion_fn=fake)
    t0 = time.time()
    resp, used = r.complete([])
    ok("hang_used_fallback", used == "F")
    ok("hang_bounded_fast", (time.time() - t0) < 1.5)   # didn't wait the 2s hang


def test_breaker_opens_after_threshold():
    fake = FakeLLM({"P": "raise"})
    r = lc.ResilientLLM("P", fallback="F", timeout_s=1.0, breaker_threshold=2, completion_fn=fake)
    for _ in range(4):
        r.complete([])
    ok("breaker_open", r.breaker_open is True)
    ok("breaker_primary_stopped", fake.calls.count("P") == 2)   # not retried after it opened
    ok("breaker_effective_model", r.effective_model() == "F")


def test_no_fallback_raises():
    fake = FakeLLM({"P": "raise"})
    r = lc.ResilientLLM("P", fallback=None, timeout_s=1.0, completion_fn=fake)
    try:
        r.complete([])
        ok("no_fb_raises", False)
    except RuntimeError:
        ok("no_fb_raises", True)


def test_no_fallback_still_bounded():
    fake = FakeLLM({"P": "hang"})
    r = lc.ResilientLLM("P", fallback=None, timeout_s=0.3, completion_fn=fake)
    try:
        r.complete([])
        ok("no_fb_bounded", False)
    except lc.LLMTimeout:
        ok("no_fb_bounded", True)


def test_same_primary_and_fallback_disables_fallback():
    r = lc.ResilientLLM("P", fallback="P", timeout_s=1.0, completion_fn=FakeLLM())
    ok("same_model_no_fallback", r.fallback is None)


# ---- resilient_from_config ----
def test_from_config_defaults():
    cfg = {"classifier_model": "gemini/x", "llm_request_timeout_seconds": 45, "llm_breaker_threshold": 2}
    r = lc.resilient_from_config(cfg, "classifier_model", "classifier_fallback_model",
                                 "gemini/default", completion_fn=FakeLLM())
    ok("cfg_primary", r.primary == "gemini/x")
    ok("cfg_fallback_default", r.fallback == "anthropic/claude-haiku-4-5")
    ok("cfg_timeout", r.timeout_s == 45.0)
    ok("cfg_threshold", r.breaker_threshold == 2)


def test_from_config_fallback_disabled():
    cfg = {"analyst_model": "gemini/y", "analyst_fallback_model": ""}
    r = lc.resilient_from_config(cfg, "analyst_model", "analyst_fallback_model",
                                 "gemini/default", completion_fn=FakeLLM())
    ok("cfg_fallback_off", r.fallback is None)


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
