"""
Daily cost report (NF-14) — sent to the operator's Telegram AFTER the 11:00 WhatsApp dispatch has
reached the group + Muda. Rolls up the whole day's spend from the execution_log table (per-run
trace + cost): the Telegram brief PLUS every WhatsApp chat. The WhatsApp chat list comes from the
registry, so adding chats later just works — nothing here is hard-coded to "2 groups".

Pure summarize/format; fetch_today() is the only I/O. Best-effort sender (the caller wraps it) —
a cost-report failure can never affect the briefs.

    venv\\Scripts\\python.exe tests\\test_cost_report.py
"""
from datetime import datetime, timezone, timedelta

JST = timezone(timedelta(hours=9))
# Friendly labels for the task_type buckets; unknown types fall through with their raw name.
_TASK_LABELS = {"brief": "📲 Telegram brief", "whatsapp_brief": "💬 WhatsApp"}


def jst_day_bounds(now_utc):
    """(start_of_JST_day_as_UTC_iso, 'YYYY-MM-DD' JST date) for the JST day containing now_utc."""
    now_j = now_utc.astimezone(JST)
    start_j = now_j.replace(hour=0, minute=0, second=0, microsecond=0)
    return start_j.astimezone(timezone.utc).isoformat(), now_j.date().isoformat()


def summarize(rows):
    """execution_log rows -> {total, by_task: {task: {total, by_agent: {agent: cost}}}}. Pure."""
    out = {"total": 0.0, "by_task": {}}
    for r in rows or []:
        c = float(r.get("actual_cost") or 0)
        out["total"] += c
        tt = r.get("task_type") or "other"
        bucket = out["by_task"].setdefault(tt, {"total": 0.0, "by_agent": {}})
        bucket["total"] += c
        a = r.get("agent") or "unknown"
        bucket["by_agent"][a] = bucket["by_agent"].get(a, 0.0) + c
    return out


def _money(x):
    return f"${x:.4f}"


def _agent_line(by_agent):
    parts = [f"{a} {_money(c)}" for a, c in sorted(by_agent.items(), key=lambda kv: -kv[1]) if c > 0]
    return "   " + " · ".join(parts) if parts else "   (no LLM cost)"


def format_report(summary, chat_names, jst_date, cap_usd=2.0):
    """Telegram-friendly cost report. Pure. `chat_names` (the WhatsApp chats) comes from the
    registry — dynamic, so the report grows with the chat list automatically."""
    total = summary.get("total", 0.0)
    by_task = summary.get("by_task", {})
    lines = [f"💰 NewsFramer cost — {jst_date} (JST)", f"Total: {_money(total)}", ""]

    tg = by_task.get("brief")
    if tg:
        lines.append(f"{_TASK_LABELS['brief']}: {_money(tg['total'])}")
        lines.append(_agent_line(tg["by_agent"]))

    wa = by_task.get("whatsapp_brief")
    if wa:
        n = len(chat_names or [])
        names = ", ".join(chat_names) if chat_names else "—"
        lines.append(f"{_TASK_LABELS['whatsapp_brief']} ({n} chat{'s' if n != 1 else ''}: {names}): {_money(wa['total'])}")
        lines.append(_agent_line(wa["by_agent"]))

    for tt, d in by_task.items():
        if tt not in ("brief", "whatsapp_brief"):
            lines.append(f"• {tt}: {_money(d['total'])}")

    lines.append("")
    if cap_usd and cap_usd > 0:
        pct = total / cap_usd * 100
        lines.append(f"⚠ OVER the ${cap_usd:.0f}/day cap" if total > cap_usd
                     else f"({pct:.0f}% of the ${cap_usd:.0f}/day cap)")
    return "\n".join(lines)


def fetch_today(sb, now_utc):
    """execution_log rows for the current JST day. (now_utc, jst_date)."""
    start_utc, jst_date = jst_day_bounds(now_utc)
    r = (sb.table("execution_log")
         .select("task_type, agent, actual_cost, created_at")
         .gte("created_at", start_utc).execute())
    return (r.data or []), jst_date


def build_and_send(sb, reg, config, send_fn, now_utc=None):
    """Fetch today's execution_log, summarize, format with the registry's chat list, and send via
    send_fn (the Telegram alert path). Returns the message. The caller wraps this best-effort."""
    now_utc = now_utc or datetime.now(timezone.utc)
    rows, jst_date = fetch_today(sb, now_utc)
    summary = summarize(rows)
    chat_names = [d.get("name", "?") for d in (reg.get("deliveries") or []) if d.get("target")]
    cap = float(config.get("cost_report_cap_usd", 2.0))
    msg = format_report(summary, chat_names, jst_date, cap)
    send_fn(msg)
    return msg
