# ARCHIVED 2026-07-22 — retired, not deleted (repo archive rule).
# Reason: the World Cup / football module was removed from the codebase (2026 tournament
# ended 2026-07-19; operator chose clean deletion over extracting a tournament template).
# Subject coverage now: none — the code under test no longer exists (agents/worldcup_data.py,
# agents/worldcup_format.py, run_worldcup_brief.py, agents/event_feed.py, run_football_brief.py
# and all worldcup_*/football_* config keys were deleted the same day).
# This file will no longer run: its imports were deleted with the feature.

"""
Tests for agents/event_feed.py (NF-A2) — the pure RSS-digest core (no network).
Window filtering, dedup, per-source + total caps, newest-first, format, and the
empty -> '' guard (so the runner never sends an empty WhatsApp message).

    venv\\Scripts\\python.exe tests\\test_event_feed.py
"""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
import event_feed as ef  # noqa: E402

PASS = []


def ok(name, cond):
    if not cond:
        raise AssertionError(name)
    PASS.append(name)


NOW = datetime(2026, 6, 17, 9, 0, tzinfo=timezone.utc)
RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>Guardian Football</title>
<item><title>France beat Senegal 3-1</title><link>https://g/1</link>
  <pubDate>Wed, 17 Jun 2026 06:00:00 GMT</pubDate></item>
<item><title>France beat Senegal 3-1</title><link>https://g/dup</link>
  <pubDate>Wed, 17 Jun 2026 06:05:00 GMT</pubDate></item>
<item><title>Argentina face Algeria - preview</title><link>https://g/2</link>
  <pubDate>Wed, 17 Jun 2026 07:00:00 GMT</pubDate></item>
<item><title>Old transfer rumour from last week</title><link>https://g/old</link>
  <pubDate>Mon, 08 Jun 2026 06:00:00 GMT</pubDate></item>
</channel></rss>"""


def test_parse_feed():
    items = ef.parse_feed(RSS, "Guardian")
    ok("parse_count", len(items) == 4)
    ok("parse_fields", bool(items[0]["title"]) and bool(items[0]["link"]) and items[0]["source"] == "Guardian")
    ok("parse_dt", items[0]["published"] is not None and items[0]["published"].tzinfo is not None)


def test_within_window():
    items = ef.parse_feed(RSS, "Guardian")
    kept = ef.within_window(items, NOW, 24)
    ok("window_drops_old", len(kept) == 3 and all("Old transfer" not in i["title"] for i in kept))
    undated = [{"title": "No date", "link": "x", "source": "S", "published": None}]
    ok("window_keeps_undated", ef.within_window(undated, NOW, 24) == undated)


def test_dedup():
    items = ef.within_window(ef.parse_feed(RSS, "Guardian"), NOW, 24)
    deduped = ef.dedup(items)
    ok("dedup_removes_dup", len(deduped) == 2)
    ok("dedup_keeps_distinct", {i["title"] for i in deduped} ==
       {"France beat Senegal 3-1", "Argentina face Algeria - preview"})


def test_cap_per_source_and_total():
    items = [{"title": f"A{i}", "link": "x", "source": "A",
              "published": datetime(2026, 6, 17, 8, i, tzinfo=timezone.utc)} for i in range(4)]
    items += [{"title": f"B{i}", "link": "x", "source": "B",
               "published": datetime(2026, 6, 17, 8, i, tzinfo=timezone.utc)} for i in range(2)]
    capped = ef.cap(items, max_total=3, max_per_source=2)
    ok("cap_total", len(capped) == 3)
    ok("cap_per_source", sum(1 for i in capped if i["source"] == "A") <= 2)


def test_cap_newest_first():
    items = [
        {"title": "older", "link": "x", "source": "A", "published": datetime(2026, 6, 17, 6, 0, tzinfo=timezone.utc)},
        {"title": "newer", "link": "x", "source": "A", "published": datetime(2026, 6, 17, 8, 0, tzinfo=timezone.utc)},
    ]
    ok("cap_newest", ef.cap(items, 1, 5)[0]["title"] == "newer")


def test_format_digest():
    ok("format_empty", ef.format_digest([], "H") == "")
    items = [{"title": "T1", "link": "https://x/1", "source": "Guardian", "published": NOW}]
    s = ef.format_digest(items, "⚽ *Football*", include_links=True, reply_line="Reply!")
    ok("format_header", s.startswith("⚽ *Football*"))
    ok("format_item", "• T1" in s and "_Guardian_" in s and "https://x/1" in s)
    ok("format_reply", s.rstrip().endswith("Reply!"))
    s2 = ef.format_digest(items, "H", include_links=False)
    ok("format_nolink", "https://x/1" not in s2 and "_Guardian_" in s2)


def test_build_message_end_to_end():
    msg = ef.build_message([("Guardian", RSS)], NOW, 24, 10, 3, "⚽ *Football*")
    ok("build_has_titles", "France beat Senegal 3-1" in msg and "Argentina face Algeria" in msg)
    ok("build_drops_old", "Old transfer" not in msg)
    ok("build_dedup_once", msg.count("France beat Senegal 3-1") == 1)
    empty = ef.build_message([("Guardian", RSS)], datetime(2026, 7, 1, 0, 0, tzinfo=timezone.utc), 24, 10, 3, "H")
    ok("build_empty_skips", empty == "")


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
