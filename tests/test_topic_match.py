"""
Tests for run_whatsapp_brief.topic_match — the WhatsApp topic filter (analyst-topic
based, NOT source based). Pins current behavior, INCLUDING the known NF-E5 false
negative, so any future keyword-list change is a deliberate, visible diff.

Pure logic over an article's analyst topics. No DB, no LLM.

    venv\\Scripts\\python.exe tests\\test_topic_match.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import run_whatsapp_brief as wa  # noqa: E402

KW = wa.DEFAULT_TOPIC_KEYWORDS
PASS = []


def ok(name, cond):
    if not cond:
        raise AssertionError(name)
    PASS.append(name)


def art(topics):
    return {"score": {"topics": topics}}


# --- on-topic is kept ------------------------------------------------------
def test_keeps_geopolitics():
    ok("geo_kept", wa.topic_match(art(["iran", "geopolitics", "sanctions"]), ["geopolitics"], KW))


def test_keeps_pakistan_substring():
    ok("pak_substring", wa.topic_match(art(["pakistan economy", "budget"]), ["pakistan"], KW))


def test_keeps_cyber():
    ok("cyber_kept", wa.topic_match(art(["ransomware", "breach"]), ["cybersecurity"], KW))


# --- off-topic is dropped --------------------------------------------------
def test_drops_off_topic_noise():
    ok("netflix_dropped", not wa.topic_match(art(["netflix", "entertainment"]), ["geopolitics"], KW))
    ok("retail_dropped", not wa.topic_match(art(["retail", "food service"]), ["geopolitics"], KW))


def test_empty_topics_dropped():
    ok("empty_dropped", not wa.topic_match(art([]), ["geopolitics"], KW))


# --- NF-E5 FIXED: genuinely geopolitical stories are now kept --------------
def test_nf_e5_genuine_geopolitics_now_kept():
    # Previously dropped (topics lacked any geo keyword). NF-E5 broadened the list:
    # "authoritarian" catches "authoritarianism"; "human trafficking" catches the second.
    ok("us_politics_kept",
       wa.topic_match(art(["us politics", "authoritarianism", "trump"]), ["geopolitics"], KW))
    ok("migration_kept",
       wa.topic_match(art(["pope", "migration", "human trafficking"]), ["geopolitics"], KW))


# --- fallback: unknown category falls back to [category] as its own keyword -
def test_unknown_category_uses_its_name_as_keyword():
    ok("fallback_keyword", wa.topic_match(art(["football", "world cup"]), ["football"], {}))
    ok("fallback_no_match", not wa.topic_match(art(["cricket"]), ["football"], {}))


# --- multi-category: matches if ANY category matches -----------------------
def test_any_category_matches():
    a = art(["ransomware"])
    ok("any_of_two", wa.topic_match(a, ["geopolitics", "cybersecurity"], KW))


# --- NF-C2 is_fresh: the second-slot freshness gate ------------------------
from datetime import datetime, timezone, timedelta  # noqa: E402

NOW = datetime(2026, 6, 15, 2, 0, tzinfo=timezone.utc)  # 11:00 JST


def test_is_fresh_recent_true():
    ok("fresh_2h", wa.is_fresh((NOW - timedelta(hours=2)).isoformat(), NOW, 6))
    ok("fresh_zulu", wa.is_fresh("2026-06-15T00:30:00Z", NOW, 6))      # 1.5h ago


def test_is_fresh_old_false():
    ok("stale_8h", not wa.is_fresh((NOW - timedelta(hours=8)).isoformat(), NOW, 6))
    ok("stale_boundary", not wa.is_fresh((NOW - timedelta(hours=6, minutes=1)).isoformat(), NOW, 6))


def test_is_fresh_naive_timestamp_treated_utc():
    ok("naive_ok", wa.is_fresh("2026-06-15T00:30:00", NOW, 6))          # no tz -> assume UTC, 1.5h ago


def test_is_fresh_bad_input_not_fresh():
    ok("blank", not wa.is_fresh("", NOW, 6))
    ok("none", not wa.is_fresh(None, NOW, 6))
    ok("garbage", not wa.is_fresh("not-a-date", NOW, 6))
    ok("no_hours", not wa.is_fresh((NOW).isoformat(), NOW, None))


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
