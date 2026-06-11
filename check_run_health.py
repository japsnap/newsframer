"""
NewsFramer run-health watchdog (spec §4.5 — missed-run / partial alert).

DETECTION + NOTIFICATION ONLY. Does not run or change any engine. Intended to be
run by an OpenClaw cron command job a short grace window after a scheduled slot
(e.g. 06:30 JST for the 06:00 Telegram brief). It reads the run's artifacts in
Supabase and, if anything is wrong, pings the operator via the newsframer
Telegram bot — straight through the Telegram Bot API, independent of OpenClaw's
own delivery layer (which is one of the things this is meant to catch).

It alerts when, for today's slot:
  - no engine runs were recorded at all  -> the pipeline did not fire ("didn't run"),
  - any engine reported status partial/error  -> names the stage,
  - no fresh brief was produced  -> (quiet-day skip is flagged as info, not alarm),
  - a brief was built but never recorded as delivered.

Usage:
  python check_run_health.py --slot telegram                 # real check (sends if needed)
  python check_run_health.py --slot telegram --dry-run       # print the alert, do not send
  python check_run_health.py --slot telegram --simulate partial   # send a labelled [TEST] alert

Exit code is 0 whenever the check completed (whether or not it alerted); non-zero
only if the watchdog itself could not run (so OpenClaw's cron failure path is a
last-resort backstop).
"""
import os
import sys
import argparse
from datetime import datetime, timezone, timedelta

import requests
from dotenv import load_dotenv
from supabase import create_client

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

JST = timezone(timedelta(hours=9))
ENGINES = {"fetcher", "classifier", "deduplicator", "analyst", "writer"}
SLOT_HOUR = {"telegram": 6, "whatsapp": 11}  # JST start hour per slot
WRITER_SKIP_STATUSES = {"quiet_day_no_articles", "no_clusters"}
BAD_STATUSES = {"partial", "error", "failed"}


# --- pure detection (unit-tested) ------------------------------------------
def evaluate_health(agent_runs, fresh_briefing, deliveries_for_brief, slot="telegram"):
    """Return a list of issue dicts {sev: 'alert'|'info', stage, detail}. Empty == healthy.

    agent_runs: engine rows recorded since the slot start (today).
    fresh_briefing: the briefing row produced this slot, or None.
    deliveries_for_brief: delivery rows for that briefing's id (or []).
    """
    engine_runs = [r for r in agent_runs if r.get("agent_name") in ENGINES]
    if not engine_runs:
        return [{"sev": "alert", "stage": "pipeline",
                 "detail": "no engine runs recorded since the slot start — the run did not fire"}]

    issues = []
    for r in engine_runs:
        st = (r.get("status") or "").lower()
        if st in BAD_STATUSES:
            issues.append({"sev": "alert", "stage": r.get("agent_name") or "?",
                           "detail": f"{st}: {r.get('error') or 'no detail'}"})

    writer_skips = [r for r in engine_runs
                    if r.get("agent_name") == "writer" and (r.get("status") or "") in WRITER_SKIP_STATUSES]
    if not fresh_briefing:
        if writer_skips:
            issues.append({"sev": "info", "stage": "writer",
                           "detail": f"no brief (writer status={writer_skips[-1].get('status')}); quiet day — expected"})
        else:
            issues.append({"sev": "alert", "stage": "writer", "detail": "no fresh brief produced"})
    elif not deliveries_for_brief:
        issues.append({"sev": "alert", "stage": "delivery",
                       "detail": "brief built but not recorded as delivered (record_deliveries / send may have failed)"})
    return issues


def build_alert_text(issues, when, slot="telegram"):
    """One short message naming each failed stage. None when there is nothing to say."""
    if not issues:
        return None
    has_alert = any(i["sev"] == "alert" for i in issues)
    head = "🚨 NewsFramer alert" if has_alert else "ℹ️ NewsFramer notice"
    lines = [f"{head} — {slot} brief, {when}"]
    for i in issues:
        mark = "•" if i["sev"] == "alert" else "·"
        lines.append(f"{mark} {i['stage']}: {i['detail']}")
    return "\n".join(lines)


# --- I/O -------------------------------------------------------------------
def send_telegram(token, chat_id, text):
    """Send straight through the Telegram Bot API (bypasses OpenClaw). Returns message_id."""
    r = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
        timeout=20,
    )
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram API error: {data}")
    return data["result"]["message_id"]


def _slot_start_utc(now_jst, slot):
    start_jst = now_jst.replace(hour=SLOT_HOUR.get(slot, 6), minute=0, second=0, microsecond=0)
    return start_jst.astimezone(timezone.utc)


def gather(sb, now_jst, slot):
    """Read today's run artifacts for the slot. Returns (agent_runs, fresh_briefing, deliveries)."""
    start_utc = _slot_start_utc(now_jst, slot).isoformat()
    today_jst = now_jst.date().isoformat()

    runs = (sb.table("agent_runs")
            .select("agent_name, status, error, created_at")
            .gte("created_at", start_utc).execute()).data or []

    briefs = (sb.table("briefings")
              .select("id, created_at, date, content_en")
              .eq("date", today_jst).gte("created_at", start_utc)
              .order("created_at", desc=True).limit(1).execute()).data or []
    fresh = None
    if briefs and (briefs[0].get("content_en") or "").strip():
        fresh = briefs[0]

    deliveries = []
    if fresh:
        deliveries = (sb.table("deliveries").select("article_id, brief_id")
                      .eq("brief_id", fresh["id"]).limit(1).execute()).data or []
    return runs, fresh, deliveries


SIMULATIONS = {
    "partial": [{"sev": "alert", "stage": "classifier", "detail": "partial: 2 batch(es) failed"}],
    "norun": [{"sev": "alert", "stage": "pipeline", "detail": "no engine runs recorded since the slot start — the run did not fire"}],
    "nobrief": [{"sev": "alert", "stage": "writer", "detail": "no fresh brief produced"}],
    "delivery": [{"sev": "alert", "stage": "delivery", "detail": "brief built but not recorded as delivered"}],
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slot", choices=["telegram", "whatsapp"], default="telegram")
    ap.add_argument("--grace-minutes", type=int, default=30, help="informational; the cron schedule sets the real grace")
    ap.add_argument("--dry-run", action="store_true", help="print the alert, do not send")
    ap.add_argument("--simulate", choices=list(SIMULATIONS), help="send a labelled [TEST] alert with a synthetic issue")
    args = ap.parse_args()

    now_jst = datetime.now(JST)
    when = now_jst.strftime("%Y-%m-%d %H:%M JST")
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    try:
        if args.simulate:
            issues = SIMULATIONS[args.simulate]
            text = "[TEST] " + (build_alert_text(issues, when, args.slot) or "")
        else:
            sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
            runs, fresh, deliveries = gather(sb, now_jst, args.slot)
            issues = evaluate_health(runs, fresh, deliveries, args.slot)
            print(f"health[{args.slot}] {when}: engine_runs={len([r for r in runs if r.get('agent_name') in ENGINES])} "
                  f"fresh_brief={'yes' if fresh else 'no'} deliveries={len(deliveries)} issues={len(issues)}")
            text = build_alert_text(issues, when, args.slot)

        if not text:
            print("health OK — no alert.")
            return 0

        if args.dry_run:
            print("--- DRY RUN (not sent) ---")
            print(text)
            return 0

        if not token or not chat_id:
            print("ERROR: TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID missing; cannot alert.", file=sys.stderr)
            return 3
        mid = send_telegram(token, chat_id, text)
        print(f"ALERT SENT (telegram message_id={mid}):\n{text}")
        return 0

    except Exception as e:
        # Self-report the watchdog's own failure, best-effort, then exit non-zero so
        # OpenClaw's cron failure path is a last-resort backstop.
        msg = f"🚨 NewsFramer watchdog ERROR ({args.slot}, {when}): {type(e).__name__}: {e}"
        print(msg, file=sys.stderr)
        try:
            if token and chat_id:
                send_telegram(token, chat_id, msg)
        except Exception as e2:
            print(f"  (could not send watchdog-error alert: {e2})", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
