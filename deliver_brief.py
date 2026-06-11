"""
NewsFramer — deliver the latest fresh brief to Telegram, recording §4.3 deliveries
ONLY after a confirmed send.

Replaces the old agent-announce + record-at-emit flow (which recorded even when the
send failed, because the isolated cron agent couldn't confirm its own announce). This
script reads the latest fresh briefing, splits it into Telegram-safe chunks, sends each
via the gateway subprocess (which returns a real messageId), and records the brief's
article_ids (account=newsframer) ONLY if every chunk confirmed. On any failure it
records NOTHING and fires an alert.

Usage:
  python deliver_brief.py                 # send + record on confirmed send
  python deliver_brief.py --dry-run       # print the chunk plan; no send/record
  python deliver_brief.py --simulate-fail # force a send failure -> alert, record nothing

Exit: 0 = sent+recorded (or nothing fresh to send); 1 = send failed (alerted); 2 = no fresh brief.
"""
import os
import sys
import argparse
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
sys.path.insert(0, str(BASE_DIR / "agents"))
import deliver as dlv  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DELIV_ACCOUNT = os.getenv("NEWSFRAMER_DELIVERY_ACCOUNT", "newsframer")  # deliveries.account (matches writer dedup)
TG_ACCOUNT = os.getenv("NEWSFRAMER_TG_ACCOUNT", "newsframer")           # gateway channel account id
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
FRESH_HOURS = float(os.getenv("NEWSFRAMER_BRIEF_FRESH_HOURS", "20"))
LANG_COL = "content_en"


def load_fresh_brief(sb):
    """Latest briefing if it is fresh + non-empty. Returns (row, None) or (None, reason)."""
    r = (sb.table("briefings")
         .select(f"id, created_at, date, article_ids, {LANG_COL}")
         .order("created_at", desc=True).limit(1).execute())
    rows = r.data or []
    if not rows:
        return None, "no briefings"
    row = rows[0]
    body = row.get(LANG_COL)
    if not body or not body.strip():
        return None, "empty content"
    created = row.get("created_at")
    if created:
        try:
            ts = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - ts).total_seconds() / 3600.0
            if age > FRESH_HOURS:
                return None, f"stale ({age:.1f}h > {FRESH_HOURS}h)"
        except Exception as e:
            print(f"  WARN: bad created_at ({created}): {e}")
    return row, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print chunk plan; no send/record")
    ap.add_argument("--simulate-fail", action="store_true", help="force a send failure path")
    args = ap.parse_args()

    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
    brief, why = load_fresh_brief(sb)
    if not brief:
        print(f"deliver_brief: no fresh brief to send ({why}). Nothing sent or recorded.")
        return 2

    ids = brief.get("article_ids") or []
    chunks = dlv.split_for_telegram(brief[LANG_COL])
    print(f"deliver_brief: brief={brief['id']} date={brief.get('date')} "
          f"chunks={len(chunks)} article_ids={len(ids)}")

    if args.dry_run:
        for i, c in enumerate(chunks, 1):
            print(f"  chunk {i}: {len(c)} chars | starts: {c[:60]!r}")
        print("  DRY RUN — nothing sent or recorded.")
        return 0

    if args.simulate_fail:
        send_fn = lambda chunk: None  # noqa: E731  (force failure to exercise the alert path)
    else:
        send_fn = lambda chunk: dlv.gateway_send("telegram", TG_ACCOUNT, CHAT_ID, chunk)  # noqa: E731
    record_fn = lambda account, article_ids, brief_id: dlv.record_delivered(sb, account, article_ids, brief_id)  # noqa: E731

    res = dlv.deliver_and_record(
        ids, chunks, DELIV_ACCOUNT, brief["id"],
        send_fn=send_fn, record_fn=record_fn, alert_fn=dlv.send_alert,
        label="Telegram 06:00 brief",
    )
    print(f"deliver_brief: {res}")
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
