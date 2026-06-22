"""
OpenClaw Deduplicator Agent
---------------------------
1. Generates embeddings for any non-deleted articles missing one.
2. Finds candidate pairs within a 48h window via cosine similarity >= threshold.
3. Builds clusters using union-find.
4. Classifies each cluster:
     - 'price_event': cluster spans <12h and ANY member title/topics contain price/event keywords
     - 'analysis': everything else
5. Picks primary per cluster:
     - price_event  -> latest published_at
     - analysis     -> earliest published_at (assumes originator)
6. If min pairwise similarity in an analysis cluster is < 0.90, flags for review (keeps all, no delete).
7. Otherwise: marks cluster_id, sets duplicate_of, soft-deletes non-primary members.

Run modes:
    python agents/deduplicator.py             # DRY RUN (default) - prints actions, deletes nothing
    python agents/deduplicator.py --apply     # APPLY - performs DB changes
"""

import os
import sys
import time
import yaml
import argparse
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from litellm import embedding as litellm_embedding
from supabase import create_client
from dotenv import load_dotenv

from llm_client import embed_bounded  # 2026-06-22: hard-bound embeddings (Gemini-outage resilience)

load_dotenv()

# Windows cp1252 consoles crash printing non-Latin titles (global feeds) — make stdout
# UTF-8 so logging a cluster member can never kill the run (2026-06-16 smoke-test incident).
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def load_config():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(base_dir, "config", "models.yaml"), "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# --- Tunables (sourced from config; defaults reproduce prior behaviour). See config/models.yaml. ---
try:
    _CFG = load_config()
except Exception:
    _CFG = {}
EMBED_TEXT_CHARS = int(_CFG.get("deduplicator_embed_text_chars", 500))
PRICE_EVENT_TEXT_CHARS = int(_CFG.get("deduplicator_price_event_text_chars", 300))


def get_supabase():
    return create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_KEY"))


# Keywords that indicate volatile / time-sensitive content where latest wins
PRICE_EVENT_KEYWORDS = [
    "price", "hits", "drops", "surges", "soars", "plunge", "plunges",
    "rally", "rallies", "recovers", "breaches", "tests", "slumps",
    "crashes", "breakout", "bottoms", "tops", "all-time high", "ath",
    "%", "$", "btc", "bitcoin", "eth", "ethereum", "sol",
    "election", "ceasefire", "ruling", "verdict", "shutdown",
]


def fetch_articles(sb, window_hours):
    """Fetch non-deleted articles published within the window."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=window_hours)).isoformat()
    r = (
        sb.table("raw_articles")
        .select("id, title, content_raw, published_at, embedding, source_id")
        .is_("deleted_at", "null")
        .gte("published_at", cutoff)
        .order("published_at", desc=False)
        .execute()
    )
    return r.data


def build_text_for_embedding(article):
    title = article.get("title") or ""
    content = (article.get("content_raw") or "")[:EMBED_TEXT_CHARS]
    return f"{title}\n\n{content}".strip()


def parse_embedding(value):
    """Supabase returns pgvector as either list or string. Normalize to list of floats."""
    if value is None:
        return None
    if isinstance(value, list):
        return [float(x) for x in value]
    if isinstance(value, str):
        s = value.strip().lstrip("[").rstrip("]")
        if not s:
            return None
        return [float(x) for x in s.split(",")]
    return None


def generate_embeddings_for_missing(sb, articles, model):
    """Generates embeddings for articles missing one. Updates DB. Returns updated articles list."""
    missing = [a for a in articles if parse_embedding(a.get("embedding")) is None]
    if not missing:
        print(f"  All {len(articles)} articles already have embeddings.")
        return articles

    config = load_config()
    dimensions = int(config.get("deduplicator_embedding_dimensions", 768))
    # 2026-06-22: hard-bound each embedding call; after N CONSECUTIVE failures (provider
    # unreachable) STOP — there is no Anthropic embedding to fall back to, so the deduplicator
    # skips clustering for this run and the brief still builds (clustering just degrades), instead
    # of hanging the whole pipeline on a dead Gemini connection.
    timeout_s = float(config.get("llm_request_timeout_seconds", 60))
    breaker = int(config.get("deduplicator_embedding_breaker_threshold", 3))
    print(f"  Generating embeddings for {len(missing)} articles (model: {model}, timeout {int(timeout_s)}s)...")
    consec = 0
    for i, a in enumerate(missing, 1):
        text = build_text_for_embedding(a)
        if not text:
            continue
        try:
            response = embed_bounded(litellm_embedding, model, [text], timeout_s, dimensions=dimensions)
            vec = response["data"][0]["embedding"]
            sb.table("raw_articles").update({"embedding": vec}).eq("id", a["id"]).execute()
            a["embedding"] = vec
            consec = 0
            if i % 25 == 0 or i == len(missing):
                print(f"    [{i}/{len(missing)}] embedded")
        except Exception as e:
            consec += 1
            print(f"    [{i}/{len(missing)}] FAILED for {a['id']}: {type(e).__name__}: {e}")
            a["embedding"] = None
            if consec >= breaker:
                print(f"    EMBEDDING PROVIDER UNREACHABLE ({consec} consecutive failures) — skipping "
                      f"the remaining {len(missing) - i} embedding(s); dedup degrades to no clustering "
                      f"this run (the brief still builds).")
                break

    return articles


def cosine_similarity(v1, v2):
    """Pure-Python cosine similarity. Returns 0.0 on error."""
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot = 0.0
    n1 = 0.0
    n2 = 0.0
    for a, b in zip(v1, v2):
        dot += a * b
        n1 += a * a
        n2 += b * b
    if n1 == 0 or n2 == 0:
        return 0.0
    return dot / ((n1 ** 0.5) * (n2 ** 0.5))


def find_candidate_pairs(articles, threshold):
    """Returns list of (i, j, similarity) tuples where i < j."""
    pairs = []
    vecs = []
    for a in articles:
        v = parse_embedding(a.get("embedding"))
        vecs.append(v)

    n = len(articles)
    for i in range(n):
        if vecs[i] is None:
            continue
        for j in range(i + 1, n):
            if vecs[j] is None:
                continue
            sim = cosine_similarity(vecs[i], vecs[j])
            if sim >= threshold:
                pairs.append((i, j, sim))
    return pairs


class UnionFind:
    def __init__(self, n):
        self.parent = list(range(n))

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, x, y):
        rx, ry = self.find(x), self.find(y)
        if rx != ry:
            self.parent[rx] = ry


def build_clusters(articles, pairs):
    """Returns dict: cluster_root_index -> list of article indices."""
    uf = UnionFind(len(articles))
    for i, j, _sim in pairs:
        uf.union(i, j)

    clusters = defaultdict(list)
    for idx in range(len(articles)):
        clusters[uf.find(idx)].append(idx)

    # Keep only clusters with 2+ members
    return {root: members for root, members in clusters.items() if len(members) >= 2}


def parse_dt(s):
    if not s:
        return None
    if isinstance(s, datetime):
        return s
    # tolerate both 'Z' and '+00:00'
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def cluster_time_span_hours(members):
    times = [parse_dt(a.get("published_at")) for a in members]
    times = [t for t in times if t is not None]
    if len(times) < 2:
        return 0.0
    return (max(times) - min(times)).total_seconds() / 3600.0


def has_price_event_keywords(article):
    text = ((article.get("title") or "") + " " + (article.get("content_raw") or "")[:PRICE_EVENT_TEXT_CHARS]).lower()
    return any(kw in text for kw in PRICE_EVENT_KEYWORDS)


def classify_cluster(members, price_event_window_hours):
    """Returns 'price_event' or 'analysis'."""
    span = cluster_time_span_hours(members)
    if span <= price_event_window_hours and any(has_price_event_keywords(m) for m in members):
        return "price_event"
    return "analysis"


def min_pairwise_similarity(members, pairs_index_map):
    """Among the pairs that involve only this cluster's members, find the minimum similarity."""
    member_ids = {m["id"] for m in members}
    sims = [
        sim for (a_id, b_id), sim in pairs_index_map.items()
        if a_id in member_ids and b_id in member_ids
    ]
    return min(sims) if sims else 1.0


def pick_primary(members, cluster_type):
    """Returns the article dict that should be primary."""
    if cluster_type == "price_event":
        # Latest wins
        return max(members, key=lambda a: (parse_dt(a.get("published_at")) or datetime.min.replace(tzinfo=timezone.utc), a["id"]))
    else:
        # Earliest wins (analysis: originator)
        return min(members, key=lambda a: (parse_dt(a.get("published_at")) or datetime.max.replace(tzinfo=timezone.utc), a["id"]))


def run_deduplicator(apply_changes):
    config = load_config()
    sb = get_supabase()
    start = time.time()

    model = config.get("deduplicator_embedding_model", "gemini/text-embedding-004")
    threshold = float(config.get("deduplicator_similarity_threshold", 0.85))
    window_hours = int(config.get("deduplicator_window_hours", 48))
    price_event_window = int(config.get("deduplicator_price_event_window_hours", 12))
    high_sim = float(config.get("deduplicator_high_similarity_threshold", 0.90))

    mode = "APPLY" if apply_changes else "DRY RUN"
    print(f"OpenClaw Deduplicator [{mode}]")
    print(f"  Model:                   {model}")
    print(f"  Similarity threshold:    {threshold}")
    print(f"  Time window:             {window_hours}h")
    print(f"  Price-event sub-window:  {price_event_window}h")
    print(f"  High-similarity gate:    {high_sim}\n")

    articles = fetch_articles(sb, window_hours)
    if not articles:
        print("No articles in window. Exiting.")
        return

    print(f"Fetched {len(articles)} articles in {window_hours}h window.")
    articles = generate_embeddings_for_missing(sb, articles, model)

    pairs = find_candidate_pairs(articles, threshold)
    print(f"Candidate pairs (sim >= {threshold}): {len(pairs)}")

    if not pairs:
        print("No duplicate clusters. Exiting.")
        return

    pairs_index_map = {(articles[i]["id"], articles[j]["id"]): sim for i, j, sim in pairs}
    clusters = build_clusters(articles, pairs)
    print(f"Clusters with 2+ members: {len(clusters)}\n")

    flagged_for_review = 0
    to_delete = []          # list of (loser_article, primary_id, cluster_type, sim_min)
    cluster_updates = []    # list of (article_id, cluster_id)

    for root, member_indices in clusters.items():
        members = [articles[i] for i in member_indices]
        cluster_type = classify_cluster(members, price_event_window)
        sim_min = min_pairwise_similarity(members, pairs_index_map)
        primary = pick_primary(members, cluster_type)

        flag_review = (cluster_type == "analysis" and sim_min < high_sim)

        print("-" * 80)
        if flag_review:
            status_str = "REVIEW FLAGGED — keeping all"
        else:
            status_str = f"primary={primary['id'][:8]}"
        print(f"Cluster ({cluster_type}) | members={len(members)} | min_sim={sim_min:.3f} | {status_str}")

        for m in members:
            mark = " <-- primary" if m["id"] == primary["id"] and not flag_review else ""
            print(f"  [{m['id'][:8]}] {m.get('published_at')} | {(m.get('title') or '')[:80]}{mark}")

        # Always set cluster_id (even on flagged) so Writer can query the full cluster later
        for m in members:
            cluster_updates.append((m["id"], primary["id"]))

        if not flag_review:
            for m in members:
                if m["id"] != primary["id"]:
                    to_delete.append((m, primary["id"], cluster_type, sim_min))
        else:
            flagged_for_review += 1

    print("\n" + "=" * 80)
    print(f"SUMMARY")
    print(f"  Total clusters:          {len(clusters)}")
    print(f"  Flagged for review:      {flagged_for_review}")
    print(f"  Articles to soft-delete: {len(to_delete)}")
    print(f"  cluster_id assignments:  {len(cluster_updates)}")

    if not apply_changes:
        print("\nDRY RUN — no DB changes made. Re-run with --apply to commit.")
        return

    print("\nApplying changes...")
    for article_id, cluster_id in cluster_updates:
        sb.table("raw_articles").update({"cluster_id": cluster_id}).eq("id", article_id).execute()

    for loser, primary_id, cluster_type, sim_min in to_delete:
        sb.table("raw_articles").update({
            "deleted_at": datetime.now(timezone.utc).isoformat(),
            "deleted_by": "deduplicator",
            "deletion_reason": f"duplicate of {primary_id} (cluster_type={cluster_type}, sim_min={sim_min:.3f})",
            "duplicate_of": primary_id,
        }).eq("id", loser["id"]).execute()

    duration_ms = int((time.time() - start) * 1000)
    from run_log import record_run  # NF-14: route through the shared logger (agent_runs + execution_log mirror)
    record_run(sb, {
        "agent_name": "deduplicator",
        "model_used": model,
        "tokens_in": 0,
        "tokens_out": 0,
        "cost_usd": 0.0,
        "duration_ms": duration_ms,
        "status": "success",
    })

    print(f"\nDone. {len(to_delete)} articles soft-deleted, {len(cluster_updates)} cluster_id values set.")
    print(f"Time: {duration_ms}ms")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Actually perform DB changes. Default is dry run.")
    args = parser.parse_args()
    run_deduplicator(apply_changes=args.apply)