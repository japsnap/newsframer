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
import time
import argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
sys.path.insert(0, str(BASE_DIR / "agents"))
import deliver as dlv  # noqa: E402
import surface_render as srf  # noqa: E402  (2026-06-19: per-surface Telegram render — item 2)
from brief_select import pick_best_brief  # noqa: E402  (NF-F4: deliver today's most-complete brief)

JST = timezone(timedelta(hours=int(dlv._load_cfg().get("operator_tz_offset_hours", 9))))  # NF-F4: briefs dated in JST (operator tz)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DELIV_ACCOUNT = os.getenv("NEWSFRAMER_DELIVERY_ACCOUNT", "newsframer")  # deliveries.account (matches writer dedup)
TG_ACCOUNT = os.getenv("NEWSFRAMER_TG_ACCOUNT", "newsframer")           # gateway channel account id
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
FRESH_HOURS = float(os.getenv("NEWSFRAMER_BRIEF_FRESH_HOURS", "20"))
LANG_COL = "content_en"


def _load_models_cfg():
    """Read config/models.yaml for tunables. Wrapped so a missing/broken config falls
    back to defaults rather than breaking import (CLAUDE.md no-hard-coding hard rule)."""
    try:
        import yaml
        with open(BASE_DIR / "config" / "models.yaml", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


_CFG = _load_models_cfg()
# Safety net (no-delivery incident 2026-06-14): wait up to WAIT_SECONDS for today's
# fresh brief before giving up, so a build that commits just after deliver starts is
# not missed. Env overrides config; the config default 0 reproduces the old no-wait path.
WAIT_SECONDS = float(os.getenv("NEWSFRAMER_DELIVER_WAIT_SECONDS", _CFG.get("deliver_wait_seconds", 0)))
POLL_SECONDS = float(os.getenv("NEWSFRAMER_DELIVER_POLL_SECONDS", _CFG.get("deliver_poll_seconds", 15)))
# IDEMPOTENT DELIVERY (retry-redelivery fix): skip the send if today's brief was already delivered
# to this surface. Default on; set delivery_idempotent: false to restore the old always-send path.
DELIVERY_IDEMPOTENT = bool(_CFG.get("delivery_idempotent", True))


def load_fresh_brief(sb):
    """Today's (JST) most-COMPLETE fresh, non-empty brief. Returns (row, None) or
    (None, reason).

    NF-F4: do NOT just take the latest by created_at — a stray second generator (the
    legacy Cloud Run container) writes a thin, UTC-dated brief ~90s after the real one
    and would win on recency. Scan the recent briefs and pick today's JST-dated, most
    complete one (see agents/brief_select.pick_best_brief)."""
    scan = int(os.getenv("NEWSFRAMER_BRIEF_SCAN", "10"))
    r = (sb.table("briefings")
         .select(f"id, created_at, date, article_ids, {LANG_COL}")
         .order("created_at", desc=True).limit(scan).execute())
    rows = r.data or []
    if not rows:
        return None, "no briefings"
    today_jst = datetime.now(JST).date().isoformat()
    return pick_best_brief(rows, today_jst, FRESH_HOURS, LANG_COL, datetime.now(timezone.utc))


def wait_for_brief(load_fn, max_wait_s, poll_s, sleep_fn=time.sleep, time_fn=time.monotonic):
    """Call load_fn() (-> (brief, reason)) until it returns a truthy brief or max_wait_s
    elapses, sleeping poll_s between tries. Returns the final (brief, reason). With
    max_wait_s <= 0 it calls load_fn exactly once (the old no-wait behaviour). sleep_fn
    and time_fn are injected so the wait is unit-testable without real time passing."""
    start = time_fn()
    brief, why = load_fn()
    while not brief and (time_fn() - start) < max_wait_s:
        sleep_fn(poll_s)
        brief, why = load_fn()
    return brief, why


def _run_critic(brief_text, cfg, dry=False):
    """NF-F1 (§10.13): pre-send quality check on the finished brief. REPORTS findings to your
    Telegram (the alert path) grouped by severity; it NEVER patches or blocks the send. Gated by
    critic_enabled (default off) and fully wrapped so it can never break delivery."""
    try:
        if not cfg.get("critic_enabled", False):
            return
        import critic
        findings = critic.critique(brief_text, max_chars=None, config=cfg)
        min_sev = cfg.get("critic_alert_min_severity", "Important")
        if findings and critic.at_or_above(findings, min_sev):
            report = critic.format_report(findings)
            if dry:
                print("  NF-F1 Critic (dry-run, not sent):\n" + report)
            else:
                dlv.send_alert(report)
                print(f"  NF-F1: Critic report sent to Telegram ({len(findings)} finding(s)).")
        else:
            print(f"  NF-F1: Critic OK ({len(findings)} finding(s); none at/above {min_sev}).")
    except Exception as e:
        print(f"  NF-F1: Critic skipped (isolated): {type(e).__name__}: {e}")


def already_delivered(sb, brief_id, account):
    """True if this brief was already recorded delivered to this surface (§4.3 deliveries row exists).
    Fail-OPEN on a query error — never suppress a real delivery because the check itself hiccuped."""
    try:
        r = (sb.table("deliveries").select("article_id")
             .eq("brief_id", brief_id).eq("account", account).limit(1).execute())
        return bool(r.data)
    except Exception as e:
        print(f"  (idempotency DB check skipped, failing open: {type(e).__name__})")
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print chunk plan; no send/record")
    ap.add_argument("--simulate-fail", action="store_true", help="force a send failure path")
    args = ap.parse_args()

    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
    wait_s = 0 if args.dry_run else WAIT_SECONDS
    if wait_s > 0:
        print(f"deliver_brief: waiting up to {int(wait_s)}s (poll {int(POLL_SECONDS)}s) "
              f"for today's fresh brief before giving up...")
    brief, why = wait_for_brief(lambda: load_fresh_brief(sb), wait_s, POLL_SECONDS)
    if not brief:
        print(f"deliver_brief: no fresh brief to send ({why}). Nothing sent or recorded.")
        return 2

    # IDEMPOTENT DELIVERY (retry-redelivery fix): if today's brief was already delivered to this
    # surface — proven by the local marker (covers the kill-before-DB-record window) OR a deliveries
    # row — skip the send so a cron retry can't duplicate it. Dry-run never sends, so it is exempt.
    if not args.dry_run and DELIVERY_IDEMPOTENT and (
        dlv.is_delivered_local(str(BASE_DIR), brief["id"], DELIV_ACCOUNT)
        or already_delivered(sb, brief["id"], DELIV_ACCOUNT)
    ):
        print(f"deliver_brief: brief {brief['id']} already delivered to {DELIV_ACCOUNT}; "
              f"skipping send (idempotent).")
        return 0

    ids = brief.get("article_ids") or []
    chunks = dlv.split_for_telegram(brief[LANG_COL])
    # item 2 (2026-06-19): render each chunk to clean Telegram markdown — clickable SOURCE name,
    # NO visible URL, headings->bold — so the gateway emits valid HTML instead of falling back to
    # plain text (where a link flattens to 'Source (URL)'). Split FIRST (on '##'), then render, so
    # chunking is unaffected. Wrapped: a render hiccup degrades to the canonical chunk, never blocks.
    try:
        chunks = [srf.render_for_telegram(c, _CFG) for c in chunks]
    except Exception as _re:
        print(f"  (telegram render skipped, sending canonical: {type(_re).__name__}: {_re})")
    print(f"deliver_brief: brief={brief['id']} date={brief.get('date')} "
          f"chunks={len(chunks)} article_ids={len(ids)}")

    # NF-F1 (§10.13): pre-send Critic — report-only, never blocks. No-op unless critic_enabled.
    _run_critic(brief.get(LANG_COL), _CFG, dry=args.dry_run)

    if args.dry_run:
        for i, c in enumerate(chunks, 1):
            print(f"  chunk {i}: {len(c)} chars | starts: {c[:60]!r}")
        print("  DRY RUN — nothing sent or recorded.")
        return 0

    if args.simulate_fail:
        send_fn = lambda chunk: None  # noqa: E731  (force failure to exercise the alert path)
    else:
        send_fn = lambda chunk: dlv.gateway_send("telegram", TG_ACCOUNT, CHAT_ID, chunk)  # noqa: E731
    def record_fn(account, article_ids, brief_id):
        # Local marker FIRST — written only here, i.e. AFTER every chunk confirmed (§4.3 honoured),
        # and BEFORE the deliveries DB write — so a kill in the send->record window still leaves proof
        # the send happened and the cron retry skips it.
        try:
            dlv.mark_delivered_local(str(BASE_DIR), brief_id, account)
        except Exception as e:
            print(f"  (local delivered-marker skipped: {type(e).__name__})")
        return dlv.record_delivered(sb, account, article_ids, brief_id)

    res = dlv.deliver_and_record(
        ids, chunks, DELIV_ACCOUNT, brief["id"],
        send_fn=send_fn, record_fn=record_fn, alert_fn=dlv.send_alert,
        label="Telegram 06:00 brief",
    )
    print(f"deliver_brief: {res}")
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
