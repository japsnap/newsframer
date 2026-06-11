"""
NewsFramer Analyst Agent
----------------------
Per-article reasoning. For each classified, non-deleted article not yet scored:
  - relevance_score 0-10 (domain interest)
  - label: CONFIRMS_HYPOTHESIS / CHALLENGES_HYPOTHESIS / NEW_SIGNAL / NEUTRAL
  - hypotheses (jsonb array): each {id: <user_context.id>, alignment: -2..+2}
                              empty array if no hypothesis matched
  - topics (text array)
  - actionability 0-3
  - perspective_invited bool
  - reasoning (1-2 sentences)
Runs with zero hypotheses if user_context has no active rows.
Idempotent via UNIQUE(article_id).
"""

import os
import json
import time
import yaml
from litellm import completion
from supabase import create_client
from dotenv import load_dotenv

from llm_json import parse_json_obj
from run_log import record_run

load_dotenv()

LLM_TEMPERATURE = 0.2
CONTENT_SNIPPET_CHARS = 1500
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2


def load_config():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(base_dir, "config", "models.yaml"), "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_analyst_prompt():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(base_dir, "prompts", "analyst", "system_prompt.txt")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def get_supabase():
    return create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_KEY"))


def load_user_context(sb):
    """Returns dict with 'interests' and 'hypotheses' lists from user_context.
    Both may be empty. Analyst runs gracefully either way.
    """
    r = (
        sb.table("user_context")
        .select("id, topic, stance, reasoning, confidence, specificity, kind, weight")
        .eq("active", True)
        .execute()
    )
    rows = r.data or []
    interests = [row for row in rows if row.get("kind") == "interest"]
    hypotheses = [row for row in rows if row.get("kind") == "hypothesis"
                  and row.get("status") in ("active", "partially_confirmed", "pending_confirmation")]
    return {"interests": interests, "hypotheses": hypotheses}


def load_sources_map(sb):
    r = sb.table("sources").select("id, name, category, publisher_bias_score").execute()
    return {s["id"]: s for s in r.data}


def load_articles_to_analyze(sb, cap, window_hours):
    """Articles within the freshness window, classified, not deleted, not already scored.

    Window-first + targeted scored-check: fetch the in-window classified articles
    (paged), then look up scores for exactly those ids (chunked). The old code pulled
    ALL analyst_scores ids in one unbounded query, which hit PostgREST's 1000-row cap
    once >1000 scores existed — so already-scored articles past the cap slipped through
    and the re-insert collided with the UNIQUE(article_id) constraint.
    """
    from datetime import datetime, timezone, timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=window_hours)).isoformat()

    # 1. Candidate articles: in window, classified (branch set), alive — paged.
    candidates = []
    PAGE = 1000
    start = 0
    while True:
        r = (
            sb.table("raw_articles")
            .select("id, source_id, title, content_raw, published_at, branch")
            .not_.is_("branch", "null")
            .is_("deleted_at", "null")
            .gte("published_at", cutoff)
            .order("published_at", desc=True)
            .range(start, start + PAGE - 1)
            .execute()
        )
        batch = r.data or []
        candidates.extend(batch)
        if len(batch) < PAGE:
            break
        start += PAGE

    # 2. Which of those are already scored? Query scores for exactly these ids.
    cand_ids = [a["id"] for a in candidates]
    scored_ids = set()
    CHUNK = 50
    for i in range(0, len(cand_ids), CHUNK):
        ids_chunk = cand_ids[i:i + CHUNK]
        sc = sb.table("analyst_scores").select("article_id").in_("article_id", ids_chunk).execute()
        for row in (sc.data or []):
            if row.get("article_id"):
                scored_ids.add(row["article_id"])

    fresh = [a for a in candidates if a["id"] not in scored_ids]
    if len(fresh) > cap:
        print(f"  WARN: {len(fresh)} eligible articles exceeds cap {cap}. Processing newest {cap} only.")
        fresh = fresh[:cap]
    return fresh


def build_context_block(context):
    """Build the prompt section listing user interests + active hypotheses."""
    interests = context.get("interests", [])
    hypotheses = context.get("hypotheses", [])

    lines = []

    lines.append("USER INTERESTS (with weights):")
    if not interests:
        lines.append("(none specified — apply default broad domain coverage)")
    else:
        for it in interests:
            w = it.get("weight")
            w_str = f"{w:+d}" if isinstance(w, int) else "0"
            lines.append(f"- topic='{it.get('topic','')}' weight={w_str}")
        lines.append("")
        lines.append(
            "WEIGHT INTERPRETATION: For each article, identify which interests it matches. "
            "Apply weight as a relevance adjustment after your initial scoring: "
            "+3 = significantly more relevant (push up ~2-3 points). "
            "+1 = mildly more relevant (push up ~1 point). "
            "0 = no adjustment. "
            "-1 = mildly less relevant (push down ~1 point). "
            "-3 = significantly less relevant (push down ~2-3 points). "
            "Final relevance_score must still respect the 0-10 calibration rule. "
            "Negative-weight topics should NOT be filtered out — still score them honestly, just lower."
        )

    lines.append("")

    lines.append("ACTIVE HYPOTHESES:")
    if not hypotheses:
        lines.append("(none currently active — set label to NEW_SIGNAL or NEUTRAL, hypotheses to [])")
    else:
        for h in hypotheses:
            lines.append(
                f"- id={h['id']} | topic={h.get('topic','')} | stance={h.get('stance','')} "
                f"| confidence={h.get('confidence','?')}/10 | reasoning={h.get('reasoning','')}"
            )

    return "\n".join(lines)


def build_user_prompt(article, sources_map):
    src = sources_map.get(article.get("source_id"), {})
    snippet = (article.get("content_raw") or "")[:CONTENT_SNIPPET_CHARS].replace("\n", " ")
    return (
        f"ARTICLE TO ANALYZE:\n"
        f"article_id: {article['id']}\n"
        f"source: {src.get('name','unknown')} ({src.get('category','unknown')})\n"
        f"bias_score: {src.get('publisher_bias_score', 0.0)}\n"
        f"branch: {article.get('branch')}\n"
        f"published_at: {article.get('published_at')}\n"
        f"title: {article.get('title')}\n"
        f"content: {snippet}\n\n"
        f"Respond with the JSON object only."
    )


def analyze_one(article, context_block, sources_map, model):
    """LLM call with retry. Returns (parsed_dict, tokens_in, tokens_out)."""
    user_prompt = build_user_prompt(article, sources_map)
    system_text = load_analyst_prompt() + "\n\n" + context_block
    messages = [
        {"role": "system", "content": system_text},
        {"role": "user", "content": user_prompt},
    ]

    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = completion(model=model, messages=messages, temperature=LLM_TEMPERATURE)
            raw = response.choices[0].message.content
            # Always a single dict; a 1-item array / fenced / prose-wrapped reply
            # is coerced. A non-object reply raises -> retry, then per-article skip.
            parsed = parse_json_obj(raw)
            usage = getattr(response, "usage", None)
            t_in = getattr(usage, "prompt_tokens", 0) if usage else 0
            t_out = getattr(usage, "completion_tokens", 0) if usage else 0
            return parsed, t_in, t_out
        except (json.JSONDecodeError, Exception) as e:
            last_err = e
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)
    raise last_err


VALID_LABELS = {"CONFIRMS_HYPOTHESIS", "CHALLENGES_HYPOTHESIS", "NEW_SIGNAL", "NEUTRAL"}


def validate_and_clean(parsed, hypothesis_ids, article):
    """Validate parsed LLM output. Returns cleaned dict ready for insert."""
    rel = parsed.get("relevance_score")
    if not isinstance(rel, int) or not (0 <= rel <= 10):
        rel = 0

    label = parsed.get("label")
    if label not in VALID_LABELS:
        label = "NEUTRAL"

    raw_hyps = parsed.get("hypotheses") or []
    clean_hyps = []
    if isinstance(raw_hyps, list):
        for h in raw_hyps:
            if not isinstance(h, dict):
                continue
            hid = h.get("id")
            align = h.get("alignment")
            if hid not in hypothesis_ids:
                continue
            if not isinstance(align, (int, float)):
                continue
            align = max(-2, min(2, int(align)))
            clean_hyps.append({"id": hid, "alignment": align})

    if label in {"CONFIRMS_HYPOTHESIS", "CHALLENGES_HYPOTHESIS"} and not clean_hyps:
        label = "NEW_SIGNAL"

    topics = parsed.get("topics") or []
    if not isinstance(topics, list):
        topics = []
    topics = [str(t).lower()[:40] for t in topics if t][:8]

    act = parsed.get("actionability")
    if not isinstance(act, int) or not (0 <= act <= 3):
        act = 0

    title = (article.get("title") or "").lower()
    branch = article.get("branch")
    breaking_signals = ("breaking", "just in", "alert", "urgent", "live:")
    has_breaking_kw = any(kw in title for kw in breaking_signals)

    if rel >= 8 and branch == "IMMEDIATE" and act < 2:
        act = 2
    if has_breaking_kw and rel >= 7 and act < 2:
        act = 2

    pi = parsed.get("perspective_invited")
    if not isinstance(pi, bool):
        pi = (rel >= 7 and label in {"NEW_SIGNAL", "CONFIRMS_HYPOTHESIS", "CHALLENGES_HYPOTHESIS"})

    reasoning = str(parsed.get("reasoning", ""))[:500]
    differentiator = str(parsed.get("differentiator", ""))[:300]

    return {
        "relevance_score": rel,
        "label": label,
        "hypotheses": clean_hyps,
        "topics": topics,
        "actionability": act,
        "perspective_invited": pi,
        "reasoning": reasoning,
        "differentiator": differentiator,
    }


def estimate_cost(config, model, tokens_in, tokens_out):
    pricing = (config.get("pricing") or {}).get(model)
    if not pricing:
        print(f"  WARN: no pricing entry for {model}; cost reported as 0")
        return 0.0
    return (tokens_in / 1_000_000) * pricing["input"] + (tokens_out / 1_000_000) * pricing["output"]


def run_analyst():
    config = load_config()
    sb = get_supabase()
    model = config.get("analyst_model", "anthropic/claude-haiku-4-5")
    cap = int(config.get("analyst_max_articles_per_run", 300))
    window_hours = int(config.get("analyst_window_hours", 30))
    start = time.time()

    print("NewsFramer Analyst starting...")
    print(f"  Model: {model}  |  Cap: {cap}")

    context = load_user_context(sb)
    interests = context["interests"]
    hypotheses = context["hypotheses"]
    hypothesis_ids = {h["id"] for h in hypotheses}
    context_block = build_context_block(context)
    print(f"  User interests:    {len(interests)}")
    print(f"  Active hypotheses: {len(hypotheses)}")

    sources_map = load_sources_map(sb)
    articles = load_articles_to_analyze(sb, cap, window_hours)
    if not articles:
        print("  No articles to analyze. Exiting.")
        return 0
    print(f"  Articles to analyze: {len(articles)}\n")

    inserted = 0
    failed = 0
    total_in = 0
    total_out = 0

    for i, article in enumerate(articles, 1):
        try:
            parsed, t_in, t_out = analyze_one(article, context_block, sources_map, model)
            total_in += t_in
            total_out += t_out
            cleaned = validate_and_clean(parsed, hypothesis_ids, article)

            sb.table("analyst_scores").insert({
                "article_id": article["id"],
                "relevance_score": cleaned["relevance_score"],
                "label": cleaned["label"],
                "hypotheses": cleaned["hypotheses"],
                "topics": cleaned["topics"],
                "actionability": cleaned["actionability"],
                "perspective_invited": cleaned["perspective_invited"],
                "reasoning": cleaned["reasoning"],
                "differentiator": cleaned["differentiator"],
                "model_used": model,
            }).execute()

            inserted += 1
            print(f"[{i}/{len(articles)}] rel={cleaned['relevance_score']} "
                  f"label={cleaned['label']:22} act={cleaned['actionability']} "
                  f"hyps={len(cleaned['hypotheses'])} | {article['title'][:60]}")
        except Exception as e:
            failed += 1
            print(f"[{i}/{len(articles)}] FAILED: {e} | {article.get('title','')[:60]}")
            continue

    duration_ms = int((time.time() - start) * 1000)
    cost = estimate_cost(config, model, total_in, total_out)
    status = "success" if failed == 0 else "partial"
    err = f"{failed} article(s) failed" if failed else None

    # Loud on silent data loss: skipped articles drop out of scoring entirely.
    if failed:
        print(f"  ALERT: analyst dropped {failed}/{len(articles)} article(s) "
              f"(unscored -> absent from the brief).")

    record_run(sb, {
        "agent_name": "analyst",
        "model_used": model,
        "tokens_in": total_in,
        "tokens_out": total_out,
        "cost_usd": round(cost, 6),
        "duration_ms": duration_ms,
        "status": status,
        "error": err,
    })

    print(f"\nAnalyst done.")
    print(f"  Inserted: {inserted}")
    print(f"  Failed:   {failed}")
    print(f"  Tokens:   in={total_in} out={total_out}")
    print(f"  Cost:     ${cost:.6f}")
    print(f"  Time:     {duration_ms}ms")
    return inserted


if __name__ == "__main__":
    run_analyst()
