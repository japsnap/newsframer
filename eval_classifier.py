"""
OpenClaw Classifier — Evaluation Script
---------------------------------------
Run after classifier.py to inspect what it did.
Outputs:
  1. Branch distribution (IMMEDIATE vs KEEP_WARM vs NULL)
  2. Articles flagged as duplicates (duplicate_count > 1)
  3. Sample of IMMEDIATE classifications (sanity check)
  4. Sample of KEEP_WARM classifications (sanity check)
  5. Junk URL audit (URLs that should have been filtered)
"""

import os
from collections import Counter
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()
sb = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_KEY"))

print("=" * 70)
print("1. BRANCH DISTRIBUTION")
print("=" * 70)
r = sb.table("raw_articles").select("branch").is_("deleted_at", "null").execute()
counts = Counter(a["branch"] for a in r.data)
total = sum(counts.values())
for branch, count in counts.most_common():
    label = branch if branch else "NULL (unclassified)"
    pct = 100 * count / total
    print(f"  {label:25} {count:4}  ({pct:.1f}%)")
print(f"  {'TOTAL':25} {total:4}")

print()
print("=" * 70)
print("2. DUPLICATES DETECTED (duplicate_count > 1)")
print("=" * 70)
r2 = (
    sb.table("raw_articles")
    .select("id, title, duplicate_count, branch")
    .gt("duplicate_count", 1)
    .is_("deleted_at", "null")
    .order("duplicate_count", desc=True)
    .execute()
)
if not r2.data:
    print("  None. (Likely batching flaw — see Issue 2 in analysis)")
else:
    print(f"  Total flagged: {len(r2.data)}")
    for a in r2.data[:15]:
        print(f"  [{a['duplicate_count']}x {a['branch']:10}] {a['title'][:80]}")

print()
print("=" * 70)
print("3. SAMPLE — IMMEDIATE (20 random)")
print("=" * 70)
r3 = (
    sb.table("raw_articles")
    .select("title, source_id")
    .eq("branch", "IMMEDIATE")
    .is_("deleted_at", "null")
    .limit(20)
    .execute()
)
for a in r3.data:
    print(f"  {a['title'][:90]}")

print()
print("=" * 70)
print("4. SAMPLE — KEEP_WARM (20)")
print("=" * 70)
r4 = (
    sb.table("raw_articles")
    .select("title")
    .eq("branch", "KEEP_WARM")
    .is_("deleted_at", "null")
    .limit(20)
    .execute()
)
for a in r4.data:
    print(f"  {a['title'][:90]}")

print()
print("=" * 70)
print("5. JUNK AUDIT — URLs that look like they should have been filtered")
print("=" * 70)
junk_signatures = [
    "x.com/",
    "wikipedia.org",
    "knowledgehub",
    "mailto:",
    "support@",
    "/feed",
    "select-plan",
]
r5 = sb.table("raw_articles").select("title, url, branch").is_("deleted_at", "null").execute()
hits = []
for a in r5.data:
    url = (a.get("url") or "").lower()
    for sig in junk_signatures:
        if sig in url:
            hits.append((sig, a))
            break
if not hits:
    print("  None.")
else:
    print(f"  Found {len(hits)} suspicious articles:")
    for sig, a in hits:
        print(f"  [{sig}] [{a['branch']}] {a['title'][:60]}")
        print(f"           {a['url'][:90]}")

print()
print("=" * 70)
print("6. AGENT_RUNS — last 5")
print("=" * 70)
r6 = (
    sb.table("agent_runs")
    .select("agent_name, model_used, tokens_in, tokens_out, cost_usd, duration_ms, status")
    .order("created_at", desc=True)
    .limit(5)
    .execute()
)
for run in r6.data:
    print(f"  {run['agent_name']:12} | {run['status']:8} | "
          f"in={run['tokens_in']:>6} out={run['tokens_out']:>5} | "
          f"${run['cost_usd']:.4f} | {run['duration_ms']}ms | {run['model_used']}")
