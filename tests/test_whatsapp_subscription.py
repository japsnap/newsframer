"""
Tests for the WhatsApp-brief-on-subscription seam. Mirrors the Telegram writer + analyst seams:
the WhatsApp brief generation AND its translation route through `claude -p` (the flat Max plan)
when `whatsapp_use_subscription` is on, falling back to the metered API on ANY failure so a run
never drops. Default OFF reproduces today's metered path byte-for-byte.

All routing is pinned deterministically (FAKE `claude -p` + FAKE litellm completion — no real
subprocess, no API, no DB):
  - subscription_complete -> builds system/user from messages, passes the configured
    model/timeout/thinking caps to cc_writer, returns a litellm-shaped response + label
  - wa_complete off        -> metered primary (today's behaviour), fallback chain intact
  - wa_complete on         -> subscription used, metered API untouched
  - wa_complete on + sub fails          -> metered primary (never drops)
  - wa_complete on + sub + primary fail -> metered fallback model (chain intact)
  - _record_llm_cost on a subscription:* label -> cost_usd 0 (flat plan, no metered $),
    tokens still recorded; metered labels still priced via estimate_cost

    venv\\Scripts\\python.exe tests\\test_whatsapp_subscription.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import run_whatsapp_brief as wa  # noqa: E402

PASS = []


def ok(name, cond):
    if not cond:
        raise AssertionError(name)
    PASS.append(name)


MSGS = [{"role": "system", "content": "SYS"}, {"role": "user", "content": "USR"}]


class _Usage:
    def __init__(self, i, o):
        self.prompt_tokens = i
        self.completion_tokens = o


class _Resp:
    def __init__(self, content, i=200, o=30):
        self.choices = [type("C", (), {"message": type("M", (), {"content": content})()})()]
        self.usage = _Usage(i, o)


class FakeCompletion:
    """Stand-in for litellm.completion; scriptable failures per model."""
    def __init__(self, fail_models=()):
        self.calls = []          # list of model names called
        self.fail_models = set(fail_models)

    def __call__(self, model=None, messages=None, temperature=None, max_tokens=None):
        self.calls.append(model)
        if model in self.fail_models:
            raise RuntimeError(f"API down for {model}")
        return _Resp(f"api-text:{model}")


class FakeCC:
    """Stand-in for cc_writer.complete_via_subscription; captures args, scriptable failure."""
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def __call__(self, system_prompt, user_prompt, model="sonnet", timeout=600, cli="claude",
                 max_thinking_tokens=0):
        self.calls.append({"system": system_prompt, "user": user_prompt, "model": model,
                           "timeout": timeout, "max_thinking_tokens": max_thinking_tokens})
        if self.fail:
            raise RuntimeError("quota exhausted")
        return "sub-text", f"subscription:claude-{model}", 111, 22


def patched(cc=None, api=None):
    """Install fakes; returns (cc, api, restore)."""
    cc = cc or FakeCC()
    api = api or FakeCompletion()
    orig_cc = wa.cc_writer.complete_via_subscription
    orig_api = wa.completion
    wa.cc_writer.complete_via_subscription = cc
    wa.completion = api

    def restore():
        wa.cc_writer.complete_via_subscription = orig_cc
        wa.completion = orig_api
    return cc, api, restore


def test_subscription_complete_routes_and_shapes():
    cfg = {"whatsapp_use_subscription": True, "whatsapp_subscription_model": "sonnet",
           "whatsapp_subscription_timeout_seconds": 123,
           "whatsapp_subscription_max_thinking_tokens": 7}
    cc, api, restore = patched()
    try:
        resp, used = wa.subscription_complete(cfg, MSGS)
        ok("sub_label", used == "subscription:sonnet")
        ok("sub_content", resp.choices[0].message.content == "sub-text")
        ok("sub_usage", (resp.usage.prompt_tokens, resp.usage.completion_tokens) == (111, 22))
        ok("sub_system_joined", cc.calls[0]["system"] == "SYS")
        ok("sub_user_joined", cc.calls[0]["user"] == "USR")
        ok("sub_model_cfg", cc.calls[0]["model"] == "sonnet")
        ok("sub_timeout_cfg", cc.calls[0]["timeout"] == 123)
        ok("sub_thinking_cfg", cc.calls[0]["max_thinking_tokens"] == 7)
        ok("sub_api_untouched", api.calls == [])
    finally:
        restore()


def test_off_is_metered_primary():
    cfg = {"whatsapp_use_subscription": False}
    cc, api, restore = patched()
    try:
        resp, used = wa.wa_complete(cfg, MSGS, "prim", "fall", 0.3, 100)
        ok("off_primary_used", used == "prim")
        ok("off_primary_called", api.calls == ["prim"])
        ok("off_sub_untouched", cc.calls == [])
        ok("off_content", resp.choices[0].message.content == "api-text:prim")
    finally:
        restore()


def test_off_falls_back_to_secondary_model():
    cfg = {}  # key absent entirely -> off (default reproduces today's behaviour)
    cc, api, restore = patched(api=FakeCompletion(fail_models={"prim"}))
    try:
        resp, used = wa.wa_complete(cfg, MSGS, "prim", "fall", 0.3, 100)
        ok("offfb_fallback_used", used == "fall")
        ok("offfb_chain", api.calls == ["prim", "fall"])
    finally:
        restore()


def test_on_uses_subscription_not_api():
    cfg = {"whatsapp_use_subscription": True}
    cc, api, restore = patched()
    try:
        resp, used = wa.wa_complete(cfg, MSGS, "prim", "fall", 0.3, 100)
        ok("on_sub_label", used == "subscription:haiku")   # default model alias
        ok("on_sub_called", len(cc.calls) == 1)
        ok("on_api_untouched", api.calls == [])
        ok("on_content", resp.choices[0].message.content == "sub-text")
    finally:
        restore()


def test_on_sub_failure_falls_back_to_metered_primary():
    cfg = {"whatsapp_use_subscription": True}
    cc, api, restore = patched(cc=FakeCC(fail=True))
    try:
        resp, used = wa.wa_complete(cfg, MSGS, "prim", "fall", 0.3, 100)
        ok("subfail_primary_used", used == "prim")
        ok("subfail_sub_tried", len(cc.calls) == 1)
        ok("subfail_api_called", api.calls == ["prim"])
    finally:
        restore()


def test_on_sub_and_primary_failure_uses_fallback_model():
    cfg = {"whatsapp_use_subscription": True}
    cc, api, restore = patched(cc=FakeCC(fail=True), api=FakeCompletion(fail_models={"prim"}))
    try:
        resp, used = wa.wa_complete(cfg, MSGS, "prim", "fall", 0.3, 100)
        ok("chain_fallback_used", used == "fall")
        ok("chain_api_calls", api.calls == ["prim", "fall"])
    finally:
        restore()


def test_record_llm_cost_subscription_is_zero():
    rows = []
    orig = wa.record_run
    wa.record_run = lambda sb, row: rows.append(row)
    try:
        cost = wa._record_llm_cost(None, {"pricing": {}}, "whatsapp_writer",
                                   "subscription:haiku", _Resp("t", 500, 50))
        ok("subcost_zero", cost == 0.0)
        ok("subcost_row_zero", rows[0]["cost_usd"] == 0.0)
        ok("subcost_tokens_kept", (rows[0]["tokens_in"], rows[0]["tokens_out"]) == (500, 50))
        ok("subcost_model_label", rows[0]["model_used"] == "subscription:haiku")
    finally:
        wa.record_run = orig


def test_record_llm_cost_metered_still_priced():
    rows = []
    orig = wa.record_run
    wa.record_run = lambda sb, row: rows.append(row)
    try:
        cfg = {"pricing": {"m1": {"input": 1.0, "output": 2.0}}}
        cost = wa._record_llm_cost(None, cfg, "whatsapp_writer", "m1", _Resp("t", 1_000_000, 500_000))
        ok("metered_cost", abs(cost - 2.0) < 1e-9)   # 1M in @$1/M + 0.5M out @$2/M
        ok("metered_row", abs(rows[0]["cost_usd"] - 2.0) < 1e-9)
    finally:
        wa.record_run = orig


def main():
    test_subscription_complete_routes_and_shapes()
    test_off_is_metered_primary()
    test_off_falls_back_to_secondary_model()
    test_on_uses_subscription_not_api()
    test_on_sub_failure_falls_back_to_metered_primary()
    test_on_sub_and_primary_failure_uses_fallback_model()
    test_record_llm_cost_subscription_is_zero()
    ok("suite_shape", True)
    test_record_llm_cost_metered_still_priced()
    print(f"{len(PASS)} checks passed, 0 test(s) failed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
