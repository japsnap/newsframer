"""
Tests for the Phase 2 reply router (agents/reply_router.py) — pure decision logic.

    venv\\Scripts\\python.exe tests\\test_reply_router.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
import reply_router as rr  # noqa: E402

PASS = []


def ok(name, cond):
    if not cond:
        raise AssertionError(name)
    PASS.append(name)


OWNERS = ["telegram:owner-test-id"]
SET = {
    "permissions": "qa",
    "rate_limit_per_day": 10,
    "max_turns_per_conversation": 8,
    "default_language": "en",
    "write_keywords": ["change", "subscribe", "settings", "language"],
    "roman_urdu_markers": ["chahiye", "batao", "han", "aur"],
}


def test_owner_exempt_and_may_write():
    # owner is over the cap AND asks to change settings -> still answers (exempt + allowed)
    d = rr.decide("change the language settings", "telegram:owner-test-id", SET, 999, OWNERS)
    ok("owner_answers", d["action"] == rr.ANSWER)


def test_non_owner_write_routes_to_owner():
    d = rr.decide("please change my language to urdu", "wa:stranger", SET, 0, OWNERS)
    ok("write_needs_approval", d["action"] == rr.OWNER_APPROVAL_REQUIRED)


def test_non_owner_rate_limited():
    over = rr.decide("what happened in the news?", "wa:stranger", SET, 10, OWNERS)
    under = rr.decide("what happened in the news?", "wa:stranger", SET, 9, OWNERS)
    ok("at_cap_denied", over["action"] == rr.DENY_RATE_LIMITED)
    ok("under_cap_answers", under["action"] == rr.ANSWER)


def test_language_detection():
    ok("roman_urdu_to_ur", rr.detect_reply_language("aur batao kya hua", SET["roman_urdu_markers"], "en") == "ur")
    ok("english_default", rr.detect_reply_language("what happened today", SET["roman_urdu_markers"], "en") == "en")
    d = rr.decide("han chahiye", "wa:stranger", SET, 0, OWNERS)
    ok("decide_carries_language", d["language"] == "ur")


def test_read_only_chat_ignored():
    s = dict(SET, permissions="read")
    ok("read_only_ignored", rr.decide("hello?", "wa:stranger", s, 0, OWNERS)["action"] == rr.IGNORED)
    # owner can still interact in a read-only chat
    ok("owner_not_ignored", rr.decide("hello?", "telegram:owner-test-id", s, 0, OWNERS)["action"] == rr.ANSWER)


def test_unlimited_when_zero():
    s = dict(SET, rate_limit_per_day=0)
    ok("zero_is_unlimited", rr.decide("q?", "wa:stranger", s, 9999, OWNERS)["action"] == rr.ANSWER)


def test_chat_settings_merge():
    cfg = {"defaults": {"rate_limit_per_day": 10, "default_language": "en"},
           "chats": {"wa:Muda": {"rate_limit_per_day": 15}}}
    ok("override_wins", rr.chat_settings("wa:Muda", cfg)["rate_limit_per_day"] == 15)
    ok("inherits_default", rr.chat_settings("wa:Muda", cfg)["default_language"] == "en")
    ok("unlisted_uses_defaults", rr.chat_settings("wa:other", cfg)["rate_limit_per_day"] == 10)


def test_conversation_turn_cap():
    over = rr.decide("another question?", "wa:stranger", SET, 0, OWNERS, turns_so_far=8)
    under = rr.decide("another question?", "wa:stranger", SET, 0, OWNERS, turns_so_far=7)
    ok("at_turn_cap_denied", over["action"] == rr.DENY_CONVERSATION_LIMIT)
    ok("under_turn_cap_answers", under["action"] == rr.ANSWER)
    # owner is exempt from the conversation cap
    ok("owner_turn_exempt", rr.decide("more?", "telegram:owner-test-id", SET, 0, OWNERS, turns_so_far=99)["action"] == rr.ANSWER)


def test_truncate_input():
    ok("short_unchanged", rr.truncate_input("hi there", 600) == "hi there")
    long = "x" * 1000
    out = rr.truncate_input(long, 600)
    ok("long_capped", len(out) <= 602 and out.endswith("…"))
    ok("zero_means_off", rr.truncate_input(long, 0) == long)


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
