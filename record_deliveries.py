"""
NewsFramer — record the latest (fresh) brief's article IDs as delivered (§4.3 set-difference).

Run by the scheduled flow when a fresh brief is emitted for delivery, so the writer never
re-selects/re-delivers those article IDs. Idempotent: deliveries has UNIQUE(article_id, account)
and we upsert with ignore-duplicates, so re-runs are safe. Records ONLY a fresh brief (so it can't
mark an old brief's articles as delivered on a quiet/failed day).

Exit codes: 0 = recorded (or nothing to record); 1 = no briefings; 2 = latest brief is stale.
"""
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

ACCOUNT = os.getenv("NEWSFRAMER_DELIVERY_ACCOUNT", "newsframer")
FRESH_HOURS = float(os.getenv("NEWSFRAMER_BRIEF_FRESH_HOURS", "20"))


def main():
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
    r = (
        sb.table("briefings")
        .select("id, created_at, article_ids")
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = r.data or []
    if not rows:
        print("record_deliveries: no briefings found", file=sys.stderr)
        sys.exit(1)

    row = rows[0]
    created = row.get("created_at")
    if created:
        try:
            ts = datetime.fromisoformat(str(created).replace("Z", "+00:00"))
            age_h = (datetime.now(timezone.utc) - ts).total_seconds() / 3600.0
            if age_h > FRESH_HOURS:
                print(f"record_deliveries: latest brief {age_h:.1f}h old; not recording", file=sys.stderr)
                sys.exit(2)
        except Exception as e:
            print(f"record_deliveries: WARN bad created_at ({created}): {e}", file=sys.stderr)

    brief_id = row.get("id")
    ids = row.get("article_ids") or []
    if not ids:
        print("record_deliveries: brief has no article_ids; nothing to record")
        return

    rows_to_insert = [{"article_id": aid, "account": ACCOUNT, "brief_id": brief_id} for aid in ids]
    sb.table("deliveries").upsert(
        rows_to_insert, on_conflict="article_id,account", ignore_duplicates=True
    ).execute()
    print(f"record_deliveries: recorded {len(rows_to_insert)} article_ids "
          f"(account={ACCOUNT}, brief={brief_id})")


if __name__ == "__main__":
    main()
