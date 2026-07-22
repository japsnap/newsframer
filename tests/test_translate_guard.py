"""
Tests for the WhatsApp translation validity guard (2026-07-22 incident).

That morning's live 11:00 run sent the Family Group a broken "Urdu" message: the
subscription model (claude -p haiku) answered the translation prompt AS AN ASSISTANT
("I appreciate you sharing this news brief, but I need to clarify my role...") and the
pipeline sent that meta-text as the translation, logged success. Nothing validated the output.

The guard: `looks_translated` (pure) checks (a) a minimum length ratio vs the source and
(b) for languages with a known target script (ur -> Arabic script), a minimum share of
letters in that script. `translate` then: invalid subscription output -> retry once on the
metered chain; still invalid -> send the ENGLISH source text + alert the operator (a readable
message beats garbage, and the dispatch loop must never crash on a bad translation).

    venv\\Scripts\\python.exe tests\\test_translate_guard.py
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


URDU = ("*نیوز فریمر بریفنگ*\n\n*امریکہ اور ایران میں فوجی کشیدگی*\n\n"
        "امریکہ نے ایران کے خلاف مسلسل گیارہ راتوں تک فضائی حملے کیے ہیں۔ "
        "وزیر دفاع نے جنگ کی مجموعی لاگت بتائی۔ برطانیہ کے نئے وزیراعظم نے "
        "امریکی حملوں کے لیے برطانوی اڈوں کے استعمال کی منظوری دی۔") * 3
META = ("I appreciate you sharing this news brief, but I need to clarify my role here. "
        "You've introduced me as a professional translator. However, I'm Claude, an AI "
        "assistant made by Anthropic. Before I proceed, I need to confirm a few things "
        "about the formatting you want and the target language you prefer.") * 3
SRC = "The US has conducted eleven consecutive nights of strikes. " * 40  # ~2300 chars


class _Usage:
    def __init__(self, i, o):
        self.prompt_tokens = i
        self.completion_tokens = o


class _Resp:
    def __init__(self, content, i=100, o=50):
        self.choices = [type("C", (), {"message": type("M", (), {"content": content})()})()]
        self.usage = _Usage(i, o)


def test_looks_translated_accepts_real_urdu():
    ok("urdu_valid", wa.looks_translated(URDU, "ur", len(URDU), {}))


def test_looks_translated_rejects_english_meta_for_urdu():
    ok("meta_rejected", not wa.looks_translated(META, "ur", len(SRC), {}))


def test_looks_translated_rejects_too_short():
    ok("short_rejected", not wa.looks_translated("ٹھیک ہے", "ur", 4000, {}))


def test_looks_translated_unknown_lang_length_only():
    long_latin = "Ceci est une traduction du texte anglais vers le francais. " * 40
    ok("unknown_lang_len_ok", wa.looks_translated(long_latin, "fr", len(long_latin), {}))
    ok("unknown_lang_len_bad", not wa.looks_translated("court", "fr", 4000, {}))


def test_translate_retries_metered_when_subscription_output_invalid():
    cfg = {"whatsapp_use_subscription": True}
    calls = {"sub": 0, "api": []}
    orig_cc, orig_api = wa.cc_writer.complete_via_subscription, wa.completion

    def fake_cc(system_prompt, user_prompt, model="sonnet", timeout=600, cli="claude",
                max_thinking_tokens=0):
        calls["sub"] += 1
        return META, "subscription:claude-haiku", 100, 50

    def fake_api(model=None, messages=None, temperature=None, max_tokens=None):
        calls["api"].append(model)
        return _Resp(URDU)

    wa.cc_writer.complete_via_subscription, wa.completion = fake_cc, fake_api
    try:
        text, used = wa.translate(cfg, SRC, "ur", "gemini/flash", sb=None)
        ok("retry_sub_tried", calls["sub"] == 1)
        ok("retry_api_used", calls["api"] == ["gemini/flash"])
        ok("retry_returns_urdu", text == URDU)
        ok("retry_used_metered_label", used == "gemini/flash")
    finally:
        wa.cc_writer.complete_via_subscription, wa.completion = orig_cc, orig_api


def test_translate_falls_back_to_english_when_all_invalid():
    cfg = {"whatsapp_use_subscription": True}
    alerts = []
    orig_cc, orig_api, orig_alert = wa.cc_writer.complete_via_subscription, wa.completion, wa.send_alert

    def fake_cc(system_prompt, user_prompt, model="sonnet", timeout=600, cli="claude",
                max_thinking_tokens=0):
        return META, "subscription:claude-haiku", 100, 50

    wa.cc_writer.complete_via_subscription = fake_cc
    wa.completion = lambda model=None, messages=None, temperature=None, max_tokens=None: _Resp(META)
    wa.send_alert = lambda msg: alerts.append(msg)
    try:
        text, used = wa.translate(cfg, SRC, "ur", "gemini/flash", sb=None)
        ok("giveup_returns_english_source", text == SRC)
        ok("giveup_label", used.startswith("untranslated:"))
        ok("giveup_alerted", len(alerts) == 1 and "ur" in alerts[0])
    finally:
        wa.cc_writer.complete_via_subscription, wa.completion, wa.send_alert = orig_cc, orig_api, orig_alert


def test_translate_valid_subscription_output_passes_through():
    cfg = {"whatsapp_use_subscription": True}
    calls = {"api": []}
    orig_cc, orig_api = wa.cc_writer.complete_via_subscription, wa.completion

    def fake_cc(system_prompt, user_prompt, model="sonnet", timeout=600, cli="claude",
                max_thinking_tokens=0):
        return URDU, "subscription:claude-haiku", 100, 50

    wa.cc_writer.complete_via_subscription = fake_cc
    wa.completion = lambda **kw: calls["api"].append(kw.get("model")) or _Resp("x")
    try:
        text, used = wa.translate(cfg, SRC, "ur", "gemini/flash", sb=None)
        ok("valid_sub_kept", text == URDU)
        ok("valid_sub_label", used == "subscription:haiku")
        ok("valid_sub_no_api", calls["api"] == [])
    finally:
        wa.cc_writer.complete_via_subscription, wa.completion = orig_cc, orig_api


def main():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print(f"{len(PASS)} checks passed, 0 test(s) failed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
