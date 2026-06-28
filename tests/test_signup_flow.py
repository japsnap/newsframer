"""
Tests for the signup elicitation pipeline (agents/signup_flow.py) — pure.

    venv\\Scripts\\python.exe tests\\test_signup_flow.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
import signup_flow as su  # noqa: E402

PASS = []


def ok(name, cond):
    if not cond:
        raise AssertionError(name)
    PASS.append(name)


TOPICS = ["geopolitics", "crypto", "pakistan", "cybersecurity"]


def test_message_asks_only_what_is_needed():
    m = su.build_signup_message(TOPICS, ["short", "medium", "long"], administrator_label="the administrator")
    ok("asks_phone", "phone number" in m.lower() and "country code" in m.lower())
    ok("lists_topics", "geopolitics" in m and "crypto" in m)
    ok("lists_lengths", "short" in m and "medium" in m and "long" in m)
    ok("invites_new_topic", "topic you don't see" in m.lower() or "a topic" in m.lower())
    ok("mentions_admin_approval", "the administrator" in m)


def test_extract_phone():
    ok("e164_intl", su.extract_phone("hi, my number is +81 90 1234 5678 thanks") == "+819012345678")
    ok("dashes_ok", su.extract_phone("+1-415-555-2671") == "+14155552671")
    ok("no_phone_none", su.extract_phone("just sign me up please") is None)
    ok("too_short_none", su.extract_phone("call +12") is None)


def test_match_topics_only_offered():
    found = su.match_topics("I want crypto and pakistan news", TOPICS)
    ok("finds_offered", "crypto" in found and "pakistan" in found)
    ok("ignores_offlist", "football" not in found)


def test_match_length():
    ok("finds_long", su.match_length("please keep them long", ["short", "medium", "long"]) == "long")
    ok("none_when_absent", su.match_length("crypto please", ["short", "medium", "long"]) is None)


def test_parse_signup():
    rec = su.parse_signup("+81 90 1234 5678, crypto and geopolitics, short please", TOPICS)
    ok("phone_filled", rec["phone_e164"] == "+819012345678")
    ok("topics_filled", set(rec["topics"]) == {"crypto", "geopolitics"})
    ok("length_filled", rec["length"] == "short")
    ok("has_all_fields", set(rec.keys()) == set(su.SIGNUP_FIELDS))


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
