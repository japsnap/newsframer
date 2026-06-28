"""
Independent gateway-liveness watchdog (NewsFramer).

Runs from a Windows Scheduled Task DIRECTLY — NOT through the OpenClaw gateway — so it still works
when the gateway is the thing that died. That blind spot (the §4.5 watchdog is itself a gateway cron)
let a ~2-day WhatsApp outage go silent on 2026-06-25. Each run:
  1. pings the gateway (a lightweight read-only `cron list`, short timeout);
  2. if UNREACHABLE -> restarts it (Start-ScheduledTask "OpenClaw Gateway") and alerts Telegram;
  3. if reachable -> exits quietly (no alert, no noise).
On restart OpenClaw catches up overdue crons (verified 2026-06-25), so the missed brief delivers.
Alerts go straight through the Telegram Bot API (independent of the gateway), like check_run_health.

Usage:
  python gateway_watchdog.py             # ping; restart+alert only if down
  python gateway_watchdog.py --dry-run   # ping + print what it WOULD do; never restart/alert
"""
import os
import sys
import argparse
import subprocess
from pathlib import Path
from datetime import datetime, timezone, timedelta

import yaml
import requests
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def _cfg():
    try:
        with open(BASE_DIR / "config" / "models.yaml", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


CFG = _cfg()
JST = timezone(timedelta(hours=int(CFG.get("operator_tz_offset_hours", 9))))
GATEWAY_TASK = os.getenv("OPENCLAW_GATEWAY_TASK", CFG.get("gateway_task_name", "OpenClaw Gateway"))
PING_TIMEOUT = int(CFG.get("gateway_watchdog_ping_timeout_seconds", 25))


def _openclaw_mjs():
    return os.environ.get(
        "OPENCLAW_MJS",
        os.path.join(os.environ.get("APPDATA", ""), "npm", "node_modules", "openclaw", "openclaw.mjs"),
    )


def decide(reachable):
    """Pure branch: None (can't tell) -> skip; True -> ok; False -> restart."""
    if reachable is None:
        return "skip"
    return "ok" if reachable else "restart"


def gateway_reachable(timeout=None):
    """True if the gateway answers `cron list`; False if it errors/times out; None if the CLI is
    missing (can't tell -> never act blindly)."""
    timeout = PING_TIMEOUT if timeout is None else timeout
    mjs = _openclaw_mjs()
    if not os.path.exists(mjs):
        return None
    try:
        r = subprocess.run(["node", mjs, "cron", "list"], capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0
    except Exception:
        return False


def restart_gateway():
    """Issue a restart of the gateway scheduled task. Returns (ok, detail)."""
    try:
        r = subprocess.run(
            ["powershell", "-NonInteractive", "-Command", f'Start-ScheduledTask -TaskName "{GATEWAY_TASK}"'],
            capture_output=True, text=True, timeout=60,
        )
        return r.returncode == 0, (r.stderr or r.stdout or "").strip()[-300:]
    except Exception as e:
        return False, str(e)


def alert(text):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print("  (no telegram creds; cannot alert)")
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": text, "disable_web_page_preview": True}, timeout=20,
        )
        return bool(r.json().get("ok"))
    except Exception as e:
        print(f"  alert failed: {e}")
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="ping + report; never restart or alert")
    args = ap.parse_args()

    if not bool(CFG.get("gateway_watchdog_enabled", True)):
        print("gateway_watchdog: disabled by config (gateway_watchdog_enabled=false).")
        return 0

    when = datetime.now(JST).strftime("%Y-%m-%d %H:%M JST")
    action = decide(gateway_reachable())

    if action == "skip":
        print(f"gateway_watchdog {when}: OpenClaw CLI not found — skipping (can't determine state).")
        return 0
    if action == "ok":
        print(f"gateway_watchdog {when}: gateway reachable — OK.")
        return 0

    # action == "restart": the gateway is down
    if args.dry_run:
        print(f"gateway_watchdog {when}: gateway UNREACHABLE — [DRY RUN] would restart + alert.")
        return 0
    print(f"gateway_watchdog {when}: gateway UNREACHABLE — restarting '{GATEWAY_TASK}'...")
    ok, detail = restart_gateway()
    msg = (f"🔧 NewsFramer: the OpenClaw gateway was DOWN at {when} — watchdog issued a restart "
           f"({'OK' if ok else 'FAILED: ' + detail}). Missed crons should catch up on reconnect.")
    alert(msg)
    print(msg)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
