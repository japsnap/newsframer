"""
Tests for agents/cost_report.py (NF-14) — the pure daily cost rollup (no DB).
Summarize by task_type/agent, format the Telegram report, and prove the WhatsApp chat list is
DYNAMIC (from the registry) — never hard-coded to a fixed number of groups.

    venv\\Scripts\\python.exe tests\\test_cost_report.py
"""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
import cost_report as cr  # noqa: E402

PASS = []


def ok(name, cond):
    if not cond:
        raise AssertionError(name)
    PASS.append(name)


ROWS = [
    {"task_type": "brief", "agent": "analyst", "actual_cost": 0.13},
    {"task_type": "brief", "agent": "writer", "actual_cost": 0.05},
    {"task_type": "brief", "agent": "classifier", "actual_cost": 0.04},
    {"task_type": "whatsapp_brief", "agent": "whatsapp_writer", "actual_cost": 0.03},
    {"task_type": "whatsapp_brief", "agent": "whatsapp_translate", "actual_cost": 0.02},
    {"task_type": "whatsapp_brief", "agent": "analyst", "actual_cost": 0.04},
]


def _close(a, b):
    return abs(a - b) < 1e-9


def test_summarize():
    s = cr.summarize(ROWS)
    ok("total", _close(s["total"], 0.31))
    ok("brief_total", _close(s["by_task"]["brief"]["total"], 0.22))
    ok("whatsapp_total", _close(s["by_task"]["whatsapp_brief"]["total"], 0.09))
    ok("brief_agent", _close(s["by_task"]["brief"]["by_agent"]["analyst"], 0.13))
    ok("wa_agent", _close(s["by_task"]["whatsapp_brief"]["by_agent"]["whatsapp_writer"], 0.03))


def test_summarize_empty():
    s = cr.summarize([])
    ok("empty_total", s["total"] == 0.0 and s["by_task"] == {})


def test_format_has_sections():
    m = cr.format_report(cr.summarize(ROWS), ["Happy Rana", "Muda DM"], "2026-06-18", 2.0)
    ok("has_total", "Total:" in m)
    ok("has_telegram", "Telegram brief" in m)
    ok("has_whatsapp", "WhatsApp" in m)
    ok("has_chat_names", "Happy Rana" in m and "Muda DM" in m)
    ok("has_chat_count", "2 chats" in m)
    ok("has_cap_line", "% of the $2/day cap" in m)


def test_format_dynamic_chats():
    # the chat list is NOT hard-coded — 3 chats render as 3
    m = cr.format_report(cr.summarize(ROWS), ["A", "B", "C"], "2026-06-18", 2.0)
    ok("three_chats", "3 chats: A, B, C" in m)
    m1 = cr.format_report(cr.summarize(ROWS), ["Solo"], "2026-06-18", 2.0)
    ok("singular_chat", "1 chat: Solo" in m1)


def test_format_over_cap():
    s = {"total": 3.0, "by_task": {"brief": {"total": 3.0, "by_agent": {"analyst": 3.0}}}}
    ok("over_cap", "OVER the $2/day cap" in cr.format_report(s, [], "2026-06-18", 2.0))


def test_jst_day_bounds():
    # 06-18 02:00 UTC == 06-18 11:00 JST -> the JST date is 06-18
    start, date = cr.jst_day_bounds(datetime(2026, 6, 18, 2, 0, tzinfo=timezone.utc))
    ok("jst_date", date == "2026-06-18")
    ok("start_is_prev_15utc", start.startswith("2026-06-17T15:00"))


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
