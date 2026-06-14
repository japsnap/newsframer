"""
OpenClaw Dispatcher Agent — DEPRECATED
--------------------------------------
DEPRECATED: superseded by agents/deliver.py + deliver_brief.py (the OpenClaw
confirmed-send path, spec §4.3). The daily crons never run this file; it is kept
for reference only. Do not use it for new work.

Reads the most recent un-dispatched briefing and sends it to Telegram.
Splits at ## section boundaries when content exceeds Telegram's per-message limit.
Marks briefing as dispatched after successful delivery.

Usage:
    python agents/dispatcher.py           # send most recent un-dispatched briefing
    python agents/dispatcher.py --latest  # send most recent briefing regardless of dispatch state (resend)
"""

import os
import sys
import time
import yaml
import argparse
import re
import requests
from datetime import datetime, timezone
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()


def load_config():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(base_dir, "config", "models.yaml"), "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_supabase():
    return create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_KEY"))


def fetch_briefing(sb, force_latest=False, language="en"):
    """Get the most recent briefing. If force_latest=False, only un-dispatched."""
    content_col = f"content_{language}"
    q = sb.table("briefings").select(f"id, date, {content_col}, dispatched_at, created_at")
    if not force_latest:
        q = q.is_("dispatched_at", "null")
    r = q.order("created_at", desc=True).limit(1).execute()
    if not r.data:
        return None
    row = r.data[0]
    row["content"] = row.get(content_col)
    return row


def split_at_sections(text, char_limit):
    """Split markdown at ## boundaries. Each chunk under char_limit.
    Preserves the # header on the first chunk.
    """
    if len(text) <= char_limit:
        return [text]

    # Split on ## (theme headers) but keep them attached to following content
    parts = re.split(r"(?=^## )", text, flags=re.MULTILINE)
    # parts[0] = everything before first ## (the # header + intro)
    # parts[1:] = each section starting with ##

    chunks = []
    current = ""
    for part in parts:
        if len(current) + len(part) <= char_limit:
            current += part
        else:
            if current:
                chunks.append(current.rstrip())
            # If single part is itself too long, hard-split it
            if len(part) > char_limit:
                while len(part) > char_limit:
                    # Find a paragraph break to split at
                    split_at = part.rfind("\n\n", 0, char_limit)
                    if split_at < char_limit // 2:
                        # No good break found, hard cut
                        split_at = char_limit
                    chunks.append(part[:split_at].rstrip())
                    part = part[split_at:].lstrip()
                current = part
            else:
                current = part
    if current:
        chunks.append(current.rstrip())
    return chunks


def escape_markdown_v2(text):
    """Telegram MarkdownV2 requires escaping certain characters outside of formatting.
    To keep this simple (and Writer already uses standard Markdown), use parse_mode='Markdown'
    instead of MarkdownV2 — this avoids most escaping rules.
    Function reserved for future use if we switch parse modes.
    """
    return text


def send_telegram_message(bot_token, chat_id, text, parse_mode="Markdown", timeout=15):
    """Send one message via Telegram Bot API. Returns the message_id on success."""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": True,
    }
    r = requests.post(url, json=payload, timeout=timeout)
    if r.status_code != 200:
        # Try without parse_mode if markdown parsing failed
        if "can't parse" in r.text.lower() or "bad request" in r.text.lower():
            print(f"  WARN: Markdown parse failed, retrying as plain text. Error: {r.text[:200]}")
            payload.pop("parse_mode", None)
            r = requests.post(url, json=payload, timeout=timeout)
        if r.status_code != 200:
            raise RuntimeError(f"Telegram API error {r.status_code}: {r.text}")
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram API returned not-ok: {data}")
    return data["result"]["message_id"]


def run_dispatcher(force_latest=False):
    config = load_config()
    sb = get_supabase()
    start = time.time()

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id:
        print("ERROR: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing from .env")
        sys.exit(1)

    msg_limit = int(config.get("dispatcher_telegram_msg_limit", 3800))
    language = config.get("dispatcher_target_language", "en")
    http_timeout = float(config.get("dispatcher_http_timeout_seconds", 15))
    pause_seconds = float(config.get("dispatcher_inter_message_pause_seconds", 0.5))

    print("OpenClaw Dispatcher starting...")
    print(f"  Chat ID:    {chat_id}")
    print(f"  Language:   {language}")
    print(f"  Msg limit:  {msg_limit} chars")
    print(f"  Mode:       {'latest (forced)' if force_latest else 'un-dispatched only'}")

    briefing = fetch_briefing(sb, force_latest=force_latest, language=language)
    if not briefing:
        if force_latest:
            print("No briefings in DB. Run Writer first.")
        else:
            print("No un-dispatched briefings. Nothing to send.")
            print("(Use --latest to resend most recent regardless.)")
        return

    if not briefing.get("content"):
        print(f"ERROR: Briefing {briefing['id']} has empty content_{language}.")
        return

    print(f"\nBriefing id:   {briefing['id']}")
    print(f"Created at:    {briefing.get('created_at')}")
    print(f"Length:        {len(briefing['content'])} chars")

    chunks = split_at_sections(briefing["content"], msg_limit)
    print(f"Splitting into {len(chunks)} message(s):\n")
    for i, c in enumerate(chunks, 1):
        print(f"  Chunk {i}: {len(c)} chars")

    message_ids = []
    for i, chunk in enumerate(chunks, 1):
        print(f"\nSending chunk {i}/{len(chunks)}...")
        try:
            msg_id = send_telegram_message(bot_token, chat_id, chunk, parse_mode="Markdown", timeout=http_timeout)
            message_ids.append(msg_id)
            print(f"  Sent. message_id={msg_id}")
        except Exception as e:
            print(f"  FAILED: {e}")
            duration_ms = int((time.time() - start) * 1000)
            sb.table("agent_runs").insert({
                "agent_name": "dispatcher",
                "model_used": "telegram",
                "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0,
                "duration_ms": duration_ms,
                "status": "partial" if message_ids else "failure",
                "error": str(e)[:500],
            }).execute()
            sys.exit(1)
        # Small pause between sends to avoid rate-limits
        if i < len(chunks):
            time.sleep(pause_seconds)

    # Mark briefing as dispatched
    sb.table("briefings").update({
        "dispatched_at": datetime.now(timezone.utc).isoformat(),
        "dispatch_target": f"telegram:{chat_id}",
        "dispatch_message_ids": message_ids,
    }).eq("id", briefing["id"]).execute()

    duration_ms = int((time.time() - start) * 1000)
    sb.table("agent_runs").insert({
        "agent_name": "dispatcher",
        "model_used": "telegram",
        "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0,
        "duration_ms": duration_ms,
        "status": "success",
    }).execute()

    print(f"\nDispatcher done.")
    print(f"  Messages sent: {len(message_ids)}")
    print(f"  Briefing marked dispatched.")
    print(f"  Time: {duration_ms}ms")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--latest", action="store_true",
                        help="Send most recent briefing even if already dispatched.")
    args = parser.parse_args()
    run_dispatcher(force_latest=args.latest)