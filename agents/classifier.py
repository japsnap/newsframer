"""
OpenClaw Classifier Agent
-------------------------
Reads all raw_articles where branch IS NULL (not yet classified).
Batches them (10 per LLM call) and classifies into:
  - IMMEDIATE  : price moves, breaking news, regulatory, geopolitics, confirmed launches
  - KEEP_WARM  : tech trends, market structure, long-term AI, hypothesis-related slow topics
Detects duplicate topics within each batch.
Updates raw_articles.branch and raw_articles.duplicate_count.
Logs the run to agent_runs with tokens, cost, duration.
"""

import os
import re
import json
import time
import yaml
from datetime import datetime, timezone
from litellm import completion
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()

# --- Constants ---
BATCH_SIZE = 10
CONTENT_SNIPPET_CHARS = 500
LLM_TEMPERATURE = 0.2


# --- Config ---
def load_config():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(base_dir, "config", "models.yaml")
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# --- Supabase ---
def get_supabase():
    return create_client(
        os.getenv("SUPABASE_URL"),
        os.getenv("SUPABASE_SERVICE_KEY"),
    )


# --- Data loaders ---
def load_sources_map(sb):
    """Returns {source_id: {name, category, publisher_bias_score}}"""
    result = (
        sb.table("sources")
        .select("id, name, category, publisher_bias_score")
        .execute()
    )
    return {s["id"]: s for s in result.data}


def load_unclassified_articles(sb):
    """All raw_articles where branch IS NULL and not soft-deleted.
    Sorted by published_at DESC so same-event coverage from multiple sources
    tends to cluster into the same batch for duplicate detection.
    """
    result = (
        sb.table("raw_articles")
        .select("id, source_id, title, content_raw, published_at, duplicate_count")
        .is_("branch", "null")
        .is_("deleted_at", "null")
        .order("published_at", desc=True)
        .execute()
    )
    return result.data


# --- Prompt ---
SYSTEM_PROMPT = """You are the Classifier in OpenClaw, a personal news automation system.

Your job: given a batch of articles, classify each as IMMEDIATE or KEEP_WARM, and detect duplicate topics within the batch.

Decision rules:
- IMMEDIATE: price moves, breaking news, regulatory actions, geopolitical events, confirmed product launches. Time-sensitive, same-day relevance.
- KEEP_WARM: tech trends, market structure analysis, long-term AI trends, hypothesis-related slow-moving topics. Worth tracking 3-5 days for weekly synthesis.
- When uncertain, prefer KEEP_WARM (conservative default).

Duplicate topic detection (within this batch only):
- Two articles share a "topic" if they report on the SAME underlying event/announcement, not just the same general subject.
- Same topic: "SEC approves ETH ETF" on CoinDesk and Decrypt -> duplicates.
- Different topic: "ETF approved" vs "ETF inflows hit record" -> NOT duplicates.
- For each article in a duplicate cluster, list the OTHER article_ids in the cluster under `duplicate_topic_ids`.
- If a duplicate cluster covers an IMMEDIATE-worthy event, all members may still be tagged IMMEDIATE; the deduplication step downstream picks the representative.

Output ONLY valid JSON. No markdown fences, no commentary. Schema:
[
  {"article_id": "<uuid>", "branch": "IMMEDIATE" | "KEEP_WARM", "duplicate_topic_ids": ["<uuid>", ...]}
]
Every input article must appear exactly once in the output."""


def build_user_prompt(batch, sources_map):
    lines = ["Classify the following articles. Return JSON only.\n"]
    for a in batch:
        src = sources_map.get(a["source_id"], {})
        snippet = (a.get("content_raw") or "")[:CONTENT_SNIPPET_CHARS].replace("\n", " ")
        lines.append(
            f"---\n"
            f"article_id: {a['id']}\n"
            f"source: {src.get('name', 'unknown')} ({src.get('category', 'unknown')})\n"
            f"bias_score: {src.get('publisher_bias_score', 0.0)}\n"
            f"published_at: {a.get('published_at')}\n"
            f"title: {a.get('title')}\n"
            f"content: {snippet}\n"
        )
    return "\n".join(lines)


# --- JSON extraction (Gemini sometimes wraps in ```json fences) ---
def extract_json(raw: str):
    raw = raw.strip()
    # Strip ```json ... ``` or ``` ... ``` fences
    fence_match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", raw, re.DOTALL | re.IGNORECASE)
    if fence_match:
        raw = fence_match.group(1).strip()
    return json.loads(raw)


# --- LLM call ---
def classify_batch(batch, sources_map, model):
    user_prompt = build_user_prompt(batch, sources_map)
    response = completion(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=LLM_TEMPERATURE,
    )
    raw = response.choices[0].message.content
    parsed = extract_json(raw)

    usage = getattr(response, "usage", None)
    tokens_in = getattr(usage, "prompt_tokens", 0) if usage else 0
    tokens_out = getattr(usage, "completion_tokens", 0) if usage else 0

    return parsed, tokens_in, tokens_out


# --- Apply updates ---
def apply_classification(sb, batch, results):
    """Update branch + duplicate_count for each article in this batch.

    Validates that every result's article_id belongs to the batch (LLM hallucination guard).
    Articles missing from results are skipped (logged), not crashed on.
    """
    batch_ids = {a["id"] for a in batch}
    existing_dup_count = {a["id"]: a.get("duplicate_count", 1) for a in batch}

    seen = set()
    applied = 0
    skipped = 0

    for r in results:
        aid = r.get("article_id")
        branch = r.get("branch")
        dup_ids = r.get("duplicate_topic_ids") or []

        if aid not in batch_ids:
            print(f"    skip: article_id {aid} not in batch (LLM hallucination)")
            skipped += 1
            continue
        if branch not in ("IMMEDIATE", "KEEP_WARM"):
            print(f"    skip: {aid} bad branch '{branch}'")
            skipped += 1
            continue
        if aid in seen:
            print(f"    skip: duplicate article_id {aid} in results")
            skipped += 1
            continue
        seen.add(aid)

        # Only count dup_ids that are also in this batch
        valid_dups = [d for d in dup_ids if d in batch_ids and d != aid]
        new_count = existing_dup_count.get(aid, 1) + len(valid_dups)

        sb.table("raw_articles").update({
            "branch": branch,
            "duplicate_count": new_count,
        }).eq("id", aid).execute()
        applied += 1

    missing = batch_ids - seen
    if missing:
        print(f"    warn: {len(missing)} articles in batch had no result returned")

    return applied, skipped


# --- Cost ---
def estimate_cost(config, model, tokens_in, tokens_out):
    pricing = config.get("pricing", {}).get(model)
    if not pricing:
        print(f"  WARN: no pricing entry in models.yaml for {model}; cost reported as 0")
        return 0.0
    return (
        (tokens_in / 1_000_000) * pricing["input"]
        + (tokens_out / 1_000_000) * pricing["output"]
    )


# --- Main ---
def run_classifier():
    config = load_config()
    sb = get_supabase()
    model = config.get("classifier_model", "gemini/gemini-2.5-flash-lite")
    start_time = time.time()

    print("OpenClaw Classifier starting...")
    print(f"  Model: {model}")
    print(f"  Batch size: {BATCH_SIZE}")

    articles = load_unclassified_articles(sb)
    if not articles:
        print("  No unclassified articles. Exiting.")
        return 0

    print(f"  Loaded {len(articles)} unclassified articles")
    sources_map = load_sources_map(sb)
    print(f"  Loaded {len(sources_map)} sources for lookup")

    total_applied = 0
    total_skipped = 0
    total_tokens_in = 0
    total_tokens_out = 0
    failed_batches = 0

    num_batches = (len(articles) + BATCH_SIZE - 1) // BATCH_SIZE
    print(f"  Processing {num_batches} batches\n")

    for i in range(0, len(articles), BATCH_SIZE):
        batch = articles[i : i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        print(f"Batch {batch_num}/{num_batches} ({len(batch)} articles)...")

        try:
            results, t_in, t_out = classify_batch(batch, sources_map, model)
            total_tokens_in += t_in
            total_tokens_out += t_out

            applied, skipped = apply_classification(sb, batch, results)
            total_applied += applied
            total_skipped += skipped
            print(f"  -> applied {applied}, skipped {skipped} | tokens in={t_in} out={t_out}")
        except json.JSONDecodeError as e:
            failed_batches += 1
            print(f"  Batch {batch_num} JSON parse failed: {e}")
            continue
        except Exception as e:
            failed_batches += 1
            print(f"  Batch {batch_num} failed: {e}")
            continue

    duration_ms = int((time.time() - start_time) * 1000)
    cost = estimate_cost(config, model, total_tokens_in, total_tokens_out)
    status = "success" if failed_batches == 0 else "partial"
    error_msg = f"{failed_batches} batch(es) failed" if failed_batches else None

    sb.table("agent_runs").insert({
        "agent_name": "classifier",
        "model_used": model,
        "tokens_in": total_tokens_in,
        "tokens_out": total_tokens_out,
        "cost_usd": round(cost, 6),
        "duration_ms": duration_ms,
        "status": status,
        "error": error_msg,
    }).execute()

    print(f"\nClassifier done.")
    print(f"  Applied: {total_applied}")
    print(f"  Skipped: {total_skipped}")
    print(f"  Failed batches: {failed_batches}")
    print(f"  Tokens: in={total_tokens_in} out={total_tokens_out}")
    print(f"  Cost: ${cost:.6f}")
    print(f"  Time: {duration_ms}ms")
    return total_applied


if __name__ == "__main__":
    run_classifier()
