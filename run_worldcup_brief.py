"""
NewsFramer — daily World Cup WhatsApp message (NF-A3). Pulls the structured WC data
from Wikipedia (agents/worldcup_data), formats it (agents/worldcup_format), and
prints/sends it. SKIPS quietly when there is nothing to report (no recent results AND
no upcoming fixtures, or the tournament is over) — so it NEVER sends an empty message.

INDEPENDENT by design: this is its OWN process / OWN cron (11:00 JST), separate from
the 06:00 Telegram brief and the 11:00 WhatsApp brief. Any failure here (Wikipedia
down, parse error, send error) is caught, logged, and alerted via the newsframer bot —
it can never crash or block the other two briefs. It imports NO writer/litellm code.

SECTION ORDER: results (last 24h) -> next-24h fixtures -> group standings (all 12).
Fixture kickoffs are shown in the operator's display tz (config: worldcup_display_tz /
worldcup_display_utc_offset_hours, default Pakistan UTC+5). A closing
`worldcup_reply_line` ("Any questions, reply") is appended; reply HANDLING is NOT built
yet — member replies are only received (no auto-response wired here).

Delivery reuses the SAME path as the main WhatsApp brief: `openclaw message send` to the
`wikibot` account, to every chat in config/whatsapp_deliveries.yaml not opted out with
`worldcup: false` (the group + Muda's DM). Confirmed-send gate (§4.3 principle): a target
counts only if the gateway returns a real messageId; a failure alerts and is not counted.
The WC message carries NO DB article_ids, so nothing is recorded in `deliveries`.

TIMING: its OWN cron at **11:00 JST** (Asia/Tokyo), separate from the 06:00 Telegram and
11:00 WhatsApp jobs. Self-contained — it fetches Wikipedia live, builds, AND sends in one
process, so it needs no pre-fetch step; the last-24h / next-24h windows are relative to run time.

Usage:
  python run_worldcup_brief.py            # dry run: fetch + build + print the message
  python run_worldcup_brief.py --send     # build + post to the WhatsApp group + Muda's DM
"""
import os
import re
import sys
import subprocess
from datetime import datetime, timezone, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE, "agents"))
import worldcup_data as wd       # noqa: E402
import worldcup_format as wf     # noqa: E402
import deliver as dlv            # noqa: E402  (send_alert — lightweight: yaml + requests, no writer/litellm)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

JST = timezone(timedelta(hours=9))
REGISTRY_PATH = os.path.join(BASE, "config", "whatsapp_deliveries.yaml")
OPENCLAW_MJS = os.environ.get(
    "OPENCLAW_MJS",
    os.path.join(os.environ.get("APPDATA", ""), "npm", "node_modules", "openclaw", "openclaw.mjs"),
)


def _cfg():
    try:
        import yaml
        with open(os.path.join(BASE, "config", "models.yaml"), encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def load_registry():
    """The gitignored per-chat WhatsApp registry (group JID + DM numbers). Targets and
    numbers live ONLY here, never in tracked config."""
    try:
        import yaml
        if os.path.exists(REGISTRY_PATH):
            with open(REGISTRY_PATH, encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
    except Exception:
        pass
    return {}


def build(html, now, cfg=None):
    """(payload, formatted message). Pure given html+now+cfg — unit-testable. Reads the
    display-tz offset/label and the reply line from config (defaults reproduce current)."""
    cfg = cfg or {}
    rw = int(cfg.get("worldcup_result_window_days", 1))
    fw = int(cfg.get("worldcup_fixture_window_days", 1))
    off = cfg.get("worldcup_display_utc_offset_hours", 5)
    off = int(off) if off is not None else None
    label = cfg.get("worldcup_display_tz_label", "PKT / UTC+5")
    reply = cfg.get("worldcup_reply_line", "")
    pay = wd.build_payload(html, now, rw, fw)
    msg = wf.format_worldcup_message(
        pay["results"], pay["standings"], pay["fixtures"],
        tz_offset_hours=off, tz_label=label, reply_line=reply,
    )
    return pay, msg


def skip_reason(pay, now, end_date):
    """Why to skip (avoid an empty send): tournament over, or nothing in the windows."""
    if end_date and now.date().isoformat() > end_date:
        return f"tournament ended ({end_date})"
    if not pay["results"] and not pay["fixtures"]:
        return "no recent results and no upcoming fixtures"
    return None


# --- delivery (mirrors run_whatsapp_brief.send_whatsapp / confirmed_message_id exactly,
#     duplicated here so the WC job stays independent of the writer/litellm import chain) ---
def send_whatsapp(text, account, target):
    cmd = ["node", OPENCLAW_MJS, "message", "send", "--channel", "whatsapp",
           "--account", account, "--target", target, "--message", text, "--json"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    return r.returncode, (r.stdout or "")[-400:], (r.stderr or "")[-200:]


def confirmed_message_id(rc, stdout):
    """Confirmed only if rc==0 AND the gateway returned a real messageId."""
    if rc != 0:
        return None
    m = re.search(r'"messageId"\s*:\s*"?([^",}\s]+)', stdout or "")
    return m.group(1) if m else None


def deliver(msg, reg):
    """Send the WC message to every registry chat NOT opted out (`worldcup: false`).
    One target's failure (or exception) alerts via the newsframer bot and is not counted;
    it never stops the other targets. Returns (confirmed, attempted)."""
    account = reg.get("account", "wikibot")
    targets = [d for d in reg.get("deliveries", []) if d.get("worldcup", True) and d.get("target")]
    if not targets:
        print("  WC delivery: no WhatsApp targets (registry empty or all opted out) — nothing sent.")
        return 0, 0
    confirmed = 0
    for d in targets:
        name = d.get("name", "?")
        try:
            rc, out, err = send_whatsapp(msg, account, d["target"])
            mid = confirmed_message_id(rc, out)
            print(f"  [WC -> {name}] rc={rc} messageId={mid} {(out or '')[:120]}")
            if mid:
                confirmed += 1
            else:
                dlv.send_alert(f"🚨 NewsFramer WC: WhatsApp send FAILED for {name} (rc={rc}) — not counted.")
        except Exception as e:
            print(f"  [WC -> {name}] EXCEPTION {type(e).__name__}: {e}")
            try:
                dlv.send_alert(f"🚨 NewsFramer WC: send EXCEPTION for {name}: {type(e).__name__} — not counted.")
            except Exception:
                pass
    return confirmed, len(targets)


def main():
    send = "--send" in sys.argv[1:]
    cfg = _cfg()
    end = cfg.get("worldcup_end_date", "2026-07-19")
    now = datetime.now(JST)
    if now.date().isoformat() > end:                      # don't even fetch once it's over
        print(f"run_worldcup: tournament ended ({end}); SKIP — nothing sent.")
        return 2

    # GRACEFUL FAILURE: any fetch/parse/build error skips the WC brief with an alert.
    # Never crash, never block the independent 06:00 / 11:00 briefs.
    try:
        html = wd.fetch()
        pay, msg = build(html, now, cfg)
    except Exception as e:
        print(f"run_worldcup: SKIP — fetch/parse/build failed: {type(e).__name__}: {e}")
        try:
            dlv.send_alert(f"⚠️ NewsFramer WC: {type(e).__name__} during fetch/build — "
                           f"WC brief skipped today (the 06:00 / 11:00 briefs are unaffected).")
        except Exception:
            pass
        return 3

    why = skip_reason(pay, now, end)
    if why:
        print(f"run_worldcup: SKIP (no empty send) — {why}.")
        return 2

    print(f"run_worldcup: results={len(pay['results'])} fixtures={len(pay['fixtures'])} "
          f"standings={len(pay['standings'])} chars={len(msg)} (now {now:%Y-%m-%d %H:%M} JST)")
    print("-" * 60)
    print(msg)
    print("-" * 60)

    if not send:
        print("\nDRY RUN — nothing sent. Re-run with --send to post to the WhatsApp group + Muda's DM.")
        return 0

    reg = load_registry()
    confirmed, attempted = deliver(msg, reg)
    print(f"\nWC delivery: {confirmed}/{attempted} target(s) confirmed.")
    return 0 if (attempted and confirmed == attempted) else (1 if attempted else 0)


if __name__ == "__main__":
    sys.exit(main())
