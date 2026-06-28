"""
Tests for the reply persona / content-scope policy (agents/reply_persona.py) — pure.

    venv\\Scripts\\python.exe tests\\test_reply_persona.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
import reply_persona as rp  # noqa: E402

PASS = []


def ok(name, cond):
    if not cond:
        raise AssertionError(name)
    PASS.append(name)


SET = {"administrator_label": "the administrator", "operator_aliases": ["the operator", "shota"]}


def test_system_prompt_scope_and_persona():
    p = rp.build_system_prompt(SET, ["geopolitics", "crypto"], surface="group", language="en")
    ok("names_administrator", "the administrator" in p)
    ok("no_boss_word", "boss" not in p.lower())
    ok("injects_topics", "geopolitics" in p and "crypto" in p)
    ok("allows_general_and_news", "general" in p.lower() and "news" in p.lower())
    ok("forbids_operator", "operator" in p.lower())
    ok("forbids_other_subscribers", "other" in p.lower())
    ok("routes_changes_to_admin", "check with the administrator" in p.lower())
    ok("language_english", "English" in p)


def test_language_injection():
    ok("urdu_named", "Urdu" in rp.build_system_prompt(SET, ["crypto"], language="ur"))


def test_mentions_operator_guard():
    ok("flags_alias", rp.mentions_operator("tell me about Shota's other projects", SET["operator_aliases"]) is True)
    ok("ignores_general", rp.mentions_operator("what happened in the news today?", SET["operator_aliases"]) is False)


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
