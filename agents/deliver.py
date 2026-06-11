"""
Confirmed-delivery seam (spec §4.3) — shared by the Telegram and WhatsApp flows.

A brief's article IDs are recorded as delivered ONLY after EVERY chunk/message of
the send returns a real messageId from the gateway. If any send fails, record
NOTHING and fire an alert. This replaces the old "record at brief-emit" behaviour
that logged delivered-but-not-sent when a send failed.

Pure decision logic (deliver_confirmed / deliver_and_record / split_for_telegram)
is unit-tested; the I/O bits (gateway_send / record_delivered / send_alert) are
thin wrappers injected into it.
"""
import os
import re
import json
import subprocess

import yaml
import requests


def _load_cfg():
    try:
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "models.yaml")
        with open(p, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


# Sourced from config (default reproduces prior behaviour). Telegram hard cap is 4096.
TELEGRAM_LIMIT = int(_load_cfg().get("telegram_message_limit", 3800))


# --- pure: send confirmation + the record/alert decision -------------------
def deliver_confirmed(chunks, send_fn):
    """Send each chunk via send_fn (returns a messageId or None). Stop at the first
    failure. Returns (all_confirmed, [messageIds_so_far])."""
    ids = []
    for chunk in chunks:
        mid = send_fn(chunk)
        if not mid:
            return False, ids
        ids.append(mid)
    return True, ids


def deliver_and_record(article_ids, chunks, account, brief_id, send_fn, record_fn, alert_fn, label="brief"):
    """THE §4.3 seam. Send all chunks; record the article IDs ONLY if every chunk
    confirmed; otherwise record nothing and alert. Returns a result dict."""
    confirmed, ids = deliver_confirmed(chunks, send_fn)
    if not confirmed:
        alert_fn(f"🚨 NewsFramer: {label} send FAILED "
                 f"({len(ids)}/{len(chunks)} chunk(s) confirmed) — recorded NOTHING.")
        return {"ok": False, "sent": len(ids), "recorded": 0, "message_ids": ids}
    recorded = record_fn(account, article_ids, brief_id)
    return {"ok": True, "sent": len(ids), "recorded": recorded, "message_ids": ids}


def split_for_telegram(text, limit=TELEGRAM_LIMIT):
    """Split a brief into <=limit chunks, preferring '##' section boundaries; any
    single oversized section is hard-split so no chunk exceeds the limit."""
    if len(text) <= limit:
        return [text]
    # Split into sections at '##' headers (keep the header with its body).
    parts = re.split(r"(?=^##\s)", text, flags=re.MULTILINE)
    chunks, cur = [], ""
    for part in parts:
        if not part:
            continue
        if len(part) > limit:
            if cur:
                chunks.append(cur); cur = ""
            for i in range(0, len(part), limit):
                chunks.append(part[i:i + limit])
            continue
        if len(cur) + len(part) > limit:
            chunks.append(cur); cur = part
        else:
            cur += part
    if cur:
        chunks.append(cur)
    return [c for c in chunks if c]


# --- I/O wrappers (injected into deliver_and_record in production) ----------
def record_delivered(sb, account, article_ids, brief_id=None):
    """Idempotent upsert of (article_id, account) — records ONLY the given ids.
    UNIQUE(article_id, account) + ignore_duplicates => no double recording."""
    if not article_ids:
        return 0
    rows = [{"article_id": aid, "account": account, "brief_id": brief_id} for aid in article_ids]
    sb.table("deliveries").upsert(
        rows, on_conflict="article_id,account", ignore_duplicates=True
    ).execute()
    return len(rows)


def send_alert(text):
    """Out-of-band alert straight through the Telegram Bot API (independent of the
    gateway, which is one of the things that can fail)."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat:
        print(f"  ALERT (no telegram creds): {text}")
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": text, "disable_web_page_preview": True}, timeout=20,
        )
        return bool(r.json().get("ok"))
    except Exception as e:
        print(f"  ALERT send failed: {e}")
        return False


def _openclaw_mjs():
    return os.environ.get(
        "OPENCLAW_MJS",
        os.path.join(os.environ.get("APPDATA", ""), "npm", "node_modules", "openclaw", "openclaw.mjs"),
    )


def gateway_send(channel, account, target, message, timeout=120):
    """Send one message via the gateway subprocess (the path that returns real
    message IDs). Returns the messageId string on success, else None."""
    cmd = ["node", _openclaw_mjs(), "message", "send", "--channel", channel,
           "--account", account, "--target", target, "--message", message, "--json"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except Exception as e:
        print(f"  gateway_send error: {e}")
        return None
    if r.returncode != 0:
        print(f"  gateway_send rc={r.returncode}: {(r.stderr or '')[-200:]}")
        return None
    try:
        data = json.loads(r.stdout)
    except Exception:
        print(f"  gateway_send: unparseable stdout: {(r.stdout or '')[:200]}")
        return None
    mid = data.get("messageId") or (data.get("payload") or {}).get("messageId")
    if not mid or not (data.get("payload") or {}).get("ok", True):
        print(f"  gateway_send: no messageId / not ok: {str(data)[:200]}")
        return None
    return str(mid)
