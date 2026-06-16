"""
NF-D3 companion — READ-ONLY bias-coverage report for a delivered brief.

After NF-D1 seeded Ground-News bias on the sources, this shows the left / center / right
balance of the geopolitics + Pakistan sources that actually made it into the latest brief
(or a given briefing id). Inspection only: no writes, no LLM, no delivery — like
eval_classifier.py / print_latest_brief.py. Use it to see whether a brief leaned one way.

    venv\\Scripts\\python.exe eval_bias_coverage.py            # latest brief
    venv\\Scripts\\python.exe eval_bias_coverage.py <brief_id>  # a specific brief
"""
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

sys.path.insert(0, str(Path(__file__).resolve().parent / "agents"))
from source_skew import _norm, skew_warning  # noqa: E402  (reuse the NF-D3 logic)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = Path(__file__).resolve().parent
load_dotenv(BASE / ".env")
BIAS_CATEGORIES = ("geopolitics", "pakistan")


def main():
    sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_KEY"))
    brief_id = sys.argv[1] if len(sys.argv) > 1 else None

    q = sb.table("briefings").select("id, created_at, date, article_ids")
    q = q.eq("id", brief_id) if brief_id else q.order("created_at", desc=True).limit(1)
    rows = q.execute().data or []
    if not rows:
        print("No briefing found.")
        return 1
    b = rows[0]
    ids = b.get("article_ids") or []
    print(f"brief {b['id']}  date={b.get('date')}  created={b.get('created_at')}  article_ids={len(ids)}")
    if not ids:
        print("  (no article_ids on this brief)")
        return 0

    arts = []
    for i in range(0, len(ids), 50):
        arts += (sb.table("raw_articles").select("id, source_id, title")
                 .in_("id", ids[i:i + 50]).execute().data or [])
    src_ids = sorted({a["source_id"] for a in arts if a.get("source_id")})
    srcs = {}
    for i in range(0, len(src_ids), 50):
        for s in (sb.table("sources")
                  .select("id, name, category, groundnews_publication_bias, groundnews_factuality")
                  .in_("id", src_ids[i:i + 50]).execute().data or []):
            srcs[s["id"]] = s

    # Only geopolitics + pakistan articles carry a meaningful left/right reading.
    geo = [a for a in arts if (srcs.get(a["source_id"]) or {}).get("category") in BIAS_CATEGORIES]
    print(f"\ngeopolitics + pakistan articles in this brief: {len(geo)} / {len(arts)} total")

    lean = Counter()
    by_source = defaultdict(int)
    for a in geo:
        s = srcs.get(a["source_id"]) or {}
        lean[_norm(s.get("groundnews_publication_bias")) or "unknown"] += 1
        by_source[s.get("name") or a["source_id"]] += 1

    print("\nBias spread (by article):")
    for k in ("left", "center", "right", "unknown"):
        bar = "#" * lean.get(k, 0)
        print(f"  {k:8} {lean.get(k, 0):3}  {bar}")

    print("\nBy source (distinct sources used):")
    src_bias_pairs = []
    for name, n in sorted(by_source.items(), key=lambda kv: -kv[1]):
        sid = next((a["source_id"] for a in geo if (srcs.get(a["source_id"]) or {}).get("name") == name), None)
        s = srcs.get(sid) or {}
        raw = s.get("groundnews_publication_bias")
        print(f"  {n:2}x  {name[:26]:26}  bias={str(raw):10} fact={s.get('groundnews_factuality')}")
        src_bias_pairs.append((sid, raw))

    w = skew_warning(src_bias_pairs)
    print("\n" + ("⚠ BRIEF-LEVEL SKEW: " + w if w else "✓ No brief-level skew (both leans present, or too few placed sources)."))
    return 0


if __name__ == "__main__":
    sys.exit(main())
