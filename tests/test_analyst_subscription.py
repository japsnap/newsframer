"""
Tests for the analyst-on-subscription path (NF-ANALYST-SUB). Mirrors the writer: route analyst
scoring through `claude -p` (the flat Max plan) instead of the metered API, with an API fallback on
ANY failure so a run never silently drops. Default OFF reproduces today's API path.

These pin the wrapper's routing deterministically (a FAKE `claude -p` — no real subprocess, no API):
  - SubscriptionLLM.complete -> uses the subscription, leaves the API untouched
  - on a subscription failure -> falls back to the wrapped API llm
  - maybe_wrap_subscription -> off = identity (today); on = wraps with the configured model/timeout
  - end-to-end: score_articles over the subscription path scores every article

    venv\\Scripts\\python.exe tests\\test_analyst_subscription.py
"""
import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
import analyst as a  # noqa: E402
import cc_writer  # noqa: E402  (SubscriptionLLM routes through cc_writer.complete_via_subscription)

PASS = []


def ok(name, cond):
    if not cond:
        raise AssertionError(name)
    PASS.append(name)


def _score_obj(article_id, rel=7):
    return {"article_id": article_id, "relevance_score": rel, "label": "NEW_SIGNAL",
            "hypotheses": [], "topics": ["geopolitics"], "actionability": 1,
            "perspective_invited": True, "reasoning": "t", "differentiator": "standalone"}


# --- faithful litellm-shaped response (what the API ResilientLLM returns) ---
class _Usage:
    def __init__(self, i, o):
        self.prompt_tokens = i
        self.completion_tokens = o


class _Resp:
    def __init__(self, content, i=200, o=30):
        self.choices = [type("C", (), {"message": type("M", (), {"content": content})()})()]
        self.usage = _Usage(i, o)


class FakeAPILLM:
    """Stand-in for ResilientLLM: the surface run_analyst reads + a .complete that returns an array."""
    def __init__(self, content=None):
        self.fallback = "anthropic/claude-haiku-4-5"
        self.timeout_s = 60
        self.used_fallback = False
        self.calls = 0
        self._content = content or json.dumps([_score_obj("aaa")])

    def complete(self, messages, temperature=None):
        self.calls += 1
        return _Resp(self._content), "primary"

    def effective_model(self):
        return "gemini/gemini-2.5-flash-lite"


def _patch_cc(fn):
    """Swap cc_writer.complete_via_subscription (analyst imports the module, so this reaches it)."""
    saved = cc_writer.complete_via_subscription
    cc_writer.complete_via_subscription = fn
    return saved


# --- SubscriptionLLM routing ------------------------------------------------

def test_subscription_used_when_cc_succeeds():
    captured = {}

    def fake_cc(system, user, model="haiku", timeout=600, max_thinking_tokens=0):
        captured["system"] = system
        captured["user"] = user
        captured["model"] = model
        return json.dumps([_score_obj("aaa", 9)]), "subscription:haiku", 111, 22

    saved = _patch_cc(fake_cc)
    try:
        api = FakeAPILLM()
        llm = a.SubscriptionLLM(api, model="haiku", timeout=600, max_thinking_tokens=0)
        resp, used = llm.complete([{"role": "system", "content": "SYS"},
                                   {"role": "user", "content": "USR"}])
    finally:
        cc_writer.complete_via_subscription = saved

    ok("content_passthrough", json.loads(resp.choices[0].message.content)[0]["relevance_score"] == 9)
    ok("tokens", resp.usage.prompt_tokens == 111 and resp.usage.completion_tokens == 22)
    ok("api_untouched", api.calls == 0)
    ok("used_subscription", llm.used_subscription is True)
    ok("not_fallback", llm.used_fallback is False)
    ok("effective_is_subscription", llm.effective_model() == "subscription:haiku")
    ok("system_flattened", captured["system"] == "SYS")
    ok("user_flattened", captured["user"] == "USR")
    ok("model_passed", captured["model"] == "haiku")


def test_api_fallback_when_cc_fails():
    def boom_cc(system, user, model="haiku", timeout=600, max_thinking_tokens=0):
        raise RuntimeError("claude -p down")

    saved = _patch_cc(boom_cc)
    try:
        api = FakeAPILLM(content=json.dumps([_score_obj("bbb", 5)]))
        llm = a.SubscriptionLLM(api)
        resp, used = llm.complete([{"role": "system", "content": "S"},
                                   {"role": "user", "content": "U"}])
    finally:
        cc_writer.complete_via_subscription = saved

    ok("api_called", api.calls == 1)
    ok("fallback_content", json.loads(resp.choices[0].message.content)[0]["relevance_score"] == 5)
    ok("used_api_fallback", llm.used_api_fallback is True)
    ok("used_fallback_true", llm.used_fallback is True)
    ok("effective_is_api", llm.effective_model() == "gemini/gemini-2.5-flash-lite")


def test_proxies_api_surface():
    api = FakeAPILLM()
    llm = a.SubscriptionLLM(api)
    ok("fallback_proxied", llm.fallback == "anthropic/claude-haiku-4-5")
    ok("timeout_proxied", llm.timeout_s == 60)


# --- maybe_wrap_subscription (the config gate) ------------------------------

def test_wrap_off_is_identity():
    api = FakeAPILLM()
    ok("default_off", a.maybe_wrap_subscription(api, {}) is api)
    ok("explicit_off", a.maybe_wrap_subscription(api, {"analyst_use_subscription": False}) is api)


def test_wrap_on_wraps_with_config():
    api = FakeAPILLM()
    llm = a.maybe_wrap_subscription(api, {
        "analyst_use_subscription": True,
        "analyst_subscription_model": "sonnet",
        "analyst_subscription_timeout_seconds": 300,
        "analyst_subscription_max_thinking_tokens": 0,
    })
    ok("is_wrapped", isinstance(llm, a.SubscriptionLLM))
    ok("model_cfg", llm.model == "sonnet")
    ok("timeout_cfg", llm.timeout == 300)
    ok("wraps_api", llm.api is api)


# --- end-to-end: score_articles over the subscription path ------------------

def test_score_articles_via_subscription():
    batch = [
        {"id": "aaa", "source_id": "s", "title": "A", "content_raw": "x", "published_at": "p", "branch": "KEEP_WARM"},
        {"id": "bbb", "source_id": "s", "title": "B", "content_raw": "y", "published_at": "p", "branch": "KEEP_WARM"},
    ]
    sources = {"s": {"name": "Src", "category": "geopolitics", "publisher_bias_score": 0.0}}

    def fake_cc(system, user, model="haiku", timeout=600, max_thinking_tokens=0):
        return json.dumps([_score_obj("aaa", 8), _score_obj("bbb", 6)]), "subscription:haiku", 300, 40

    saved = _patch_cc(fake_cc)
    try:
        llm = a.SubscriptionLLM(FakeAPILLM())
        rows, failed_ids, t_in, t_out = a.score_articles(batch, "CTX", sources, set(), llm, batch_size=10)
    finally:
        cc_writer.complete_via_subscription = saved

    scored = {art["id"]: cleaned["relevance_score"] for art, cleaned in rows}
    ok("both_scored", scored == {"aaa": 8, "bbb": 6})
    ok("no_failed", failed_ids == [])
    ok("tokens_from_subscription", t_in == 300 and t_out == 40)
    ok("flagged_subscription", llm.used_subscription is True)


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
