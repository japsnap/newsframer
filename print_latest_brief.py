"""
NewsFramer — print the latest brief to stdout for OpenClaw to deliver.

Reads the most recent row from Supabase `briefings` (ordered by created_at, since
`id` is a UUID and is NOT chronological) and prints its English markdown body
(content_en). OpenClaw's scheduled task captures this stdout and delivers it to
Telegram / WhatsApp. This script never sends anything itself — delivery is
OpenClaw's job, not the old Dispatcher's.

Exit codes: 0 = printed a brief; 1 = no brief found / empty content.
"""
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

LANG_COL = "content_en"  # writer_primary_language = "en" (config/models.yaml)
# §4.5 freshness: a brief older than this counts as "no fresh brief today" (cron alerts).
FRESH_HOURS = float(os.getenv("NEWSFRAMER_BRIEF_FRESH_HOURS", "20"))


def main():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_SERVICE_KEY")
    if not url or not key:
        print("ERROR: SUPABASE_URL / SUPABASE_SERVICE_KEY missing from .env", file=sys.stderr)
        sys.exit(1)

    sb = create_client(url, key)
    r = (
        sb.table("briefings")
        .select(f"id, created_at, date, {LANG_COL}")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = r.data or []
    if not rows:
        print("ERROR: no briefings found in Supabase", file=sys.stderr)
        sys.exit(1)

    row = rows[0]
    brief = row.get(LANG_COL)
    if not brief or not brief.strip():
        print(f"ERROR: latest briefing (id={row.get('id')}) has empty {LANG_COL}", file=sys.stderr)
        sys.exit(1)

    # §4.5 freshness guard: only emit a genuinely fresh brief, so the delivery layer can tell
    # "a brief was produced today" from "the run produced nothing" (stale -> exit 2 -> alert).
    created = row.get("created_at")
    if created:
        try:
            ts = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
            age_h = (datetime.now(timezone.utc) - ts).total_seconds() / 3600.0
            if age_h > FRESH_HOURS:
                print(f"STALE: latest brief is {age_h:.1f}h old (> {FRESH_HOURS}h); no fresh brief today.", file=sys.stderr)
                sys.exit(2)
        except Exception as e:
            print(f"WARN: could not parse created_at ({created}): {e}", file=sys.stderr)

    # stdout = the brief markdown only, so OpenClaw delivers it verbatim.
    # Force UTF-8 so Japanese / Urdu / em-dashes don't crash on Windows cp1252.
    sys.stdout.reconfigure(encoding="utf-8")
    print(brief)


if __name__ == "__main__":
    main()
