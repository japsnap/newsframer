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
import sys
import json
import time
import yaml
from litellm import completion
from supabase import create_client
from dotenv import load_dotenv

from llm_json import parse_json_obj, parse_json_list
from llm_client import resilient_from_config  # 2026-06-22: timeout + fallback (Gemini-outage resilience)
import cc_writer  # NF-ANALYST-SUB: reuse the writer's `claude -p` subscription seam (claude -p)

# Windows consoles default to cp1252 and raise UnicodeEncodeError when a print contains a
# non-Latin character (Arabic/CJK/emoji titles are common now that global wires feed in).
# A crash here would kill the run mid-scoring and leave the rest unscored — make stdout
# UTF-8 so logging a title can never sink the analyst (2026-06-16 smoke-test incident).
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
from run_log import record_run

load_dotenv()


def load_config():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(base_dir, "config", "models.yaml"), "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# --- Tunables (sourced from config; defaults reproduce prior behaviour). See config/models.yaml. ---
try:
    _CFG = load_config()
except Exception:
    _CFG = {}
LLM_TEMPERATURE = float(_CFG.get("analyst_temperature", 0.2))
CONTENT_SNIPPET_CHARS = int(_CFG.get("analyst_content_snippet_chars", 1500))
MAX_RETRIES = int(_CFG.get("analyst_max_retries", 3))
RETRY_BACKOFF_SECONDS = float(_CFG.get("analyst_retry_backoff_seconds", 2))
REASONING_MAX_CHARS = int(_CFG.get("analyst_reasoning_max_chars", 500))
DIFFERENTIATOR_MAX_CHARS = int(_CFG.get("analyst_differentiator_max_chars", 300))
BREAKING_SIGNALS = tuple(_CFG.get("analyst_breaking_keywords", ("breaking", "just in", "alert", "urgent", "live:")))
ACTIONABILITY_REL_THRESHOLD = int(_CFG.get("analyst_actionability_rel_threshold", 8))
BREAKING_ACTIONABILITY_REL_THRESHOLD = int(_CFG.get("analyst_breaking_actionability_rel_threshold", 7))
PERSPECTIVE_REL_THRESHOLD = int(_CFG.get("analyst_perspective_rel_threshold", 7))
TOPIC_MAX_CHARS = int(_CFG.get("analyst_topic_max_chars", 40))
MAX_TOPICS = int(_CFG.get("analyst_max_topics", 8))

# NF-ANALYST-BATCH: batch-mode system instruction, appended after the per-article schema when
# scoring >1 article per LLM call. Config-overridable (no-hardcoding rule); in-code default kept.
_DEFAULT_BATCH_INSTRUCTION = (
    "BATCH MODE: You will receive MULTIPLE articles below, each tagged with its own article_id. "
    "Score EACH article independently using the schema above. "
    "Return ONLY a JSON ARRAY with exactly one object per article, and copy that article's "
    "article_id verbatim into an \"article_id\" field on its object. "
    "Every input article must appear exactly once in the array. No markdown fences, no commentary."
)
BATCH_INSTRUCTION = _CFG.get("analyst_batch_instruction", _DEFAULT_BATCH_INSTRUCTION)


def resolve_batch_size(config):
    """How many articles to score per LLM call. Default 10. <=1 means the per-article path
    (the documented, byte-for-byte revert to the original behaviour). A junk/missing value
    falls back to the default rather than sinking the run."""
    try:
        return int(config.get("analyst_batch_size", 10))
    except (TypeError, ValueError):
        return 10


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


def weight_interpretation_text(strong_points=3, mild_points=1):
    """The WEIGHT INTERPRETATION guidance, GENERATED from the config scale (NF-NEW14) so a future
    UI / config can tune how hard a topic weight nudges relevance — no longer hard-coded. Defaults
    reproduce the prior text byte-for-byte. Pure. `strong_points` = the nudge for a |weight|=3
    interest (rendered as a (strong-1)-strong range); `mild_points` = the nudge for a |weight|=1
    interest. The weight LABELS (+3/+1/-1/-3) stay fixed — they are the user_context.weight scale;
    only the relevance-POINTS they map to are tunable."""
    hi = int(strong_points)
    lo = max(1, hi - 1)
    rng = f"{lo}-{hi}" if lo != hi else f"{hi}"
    mid = int(mild_points)
    return (
        "WEIGHT INTERPRETATION: For each article, identify which interests it matches. "
        "Apply weight as a relevance adjustment after your initial scoring: "
        f"+3 = significantly more relevant (push up ~{rng} points). "
        f"+1 = mildly more relevant (push up ~{mid} point). "
        "0 = no adjustment. "
        f"-1 = mildly less relevant (push down ~{mid} point). "
        f"-3 = significantly less relevant (push down ~{rng} points). "
        "Final relevance_score must still respect the 0-10 calibration rule. "
        "Negative-weight topics should NOT be filtered out — still score them honestly, just lower."
    )


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
        lines.append(weight_interpretation_text(
            _CFG.get("analyst_weight_strong_points", 3),
            _CFG.get("analyst_weight_mild_points", 1)))

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


def build_batch_user_prompt(batch, sources_map):
    """Batch variant of build_user_prompt: lists N articles, each tagged with its article_id,
    and asks for a JSON ARRAY (one object per article). Mirrors the classifier's batch shape."""
    lines = [f"Analyze the following {len(batch)} articles. Return JSON only.\n"]
    for art in batch:
        src = sources_map.get(art.get("source_id"), {})
        snippet = (art.get("content_raw") or "")[:CONTENT_SNIPPET_CHARS].replace("\n", " ")
        lines.append(
            f"---\n"
            f"article_id: {art['id']}\n"
            f"source: {src.get('name','unknown')} ({src.get('category','unknown')})\n"
            f"bias_score: {src.get('publisher_bias_score', 0.0)}\n"
            f"branch: {art.get('branch')}\n"
            f"published_at: {art.get('published_at')}\n"
            f"title: {art.get('title')}\n"
            f"content: {snippet}\n"
        )
    lines.append(
        "---\n"
        "Respond with a JSON ARRAY only — one object per article, each carrying its article_id."
    )
    return "\n".join(lines)


def map_batch_results(batch, parsed_list):
    """Pure: map an LLM batch reply back to the batch by article_id.

    Returns (results_by_id, missing_ids):
      - results_by_id: {article_id -> result dict} for ids that belong to the batch (first wins
        on a duplicate; later repeats ignored). Hallucinated ids (not in the batch) are dropped.
      - missing_ids: batch articles the LLM omitted — so the caller can retry them per-article
        rather than silently losing them from scoring (data-loss guard, like the classifier).
    """
    batch_ids = {a["id"] for a in batch}
    results_by_id = {}
    if isinstance(parsed_list, list):
        for r in parsed_list:
            if not isinstance(r, dict):
                continue
            aid = r.get("article_id")
            if aid not in batch_ids or aid in results_by_id:
                continue
            results_by_id[aid] = r
    missing_ids = [a["id"] for a in batch if a["id"] not in results_by_id]
    return results_by_id, missing_ids


def analyze_batch(batch, context_block, sources_map, llm):
    """Score a batch of articles in ONE LLM call (with retry). Returns (parsed_list, t_in, t_out).
    System = the per-article schema + the BATCH_INSTRUCTION + the user-context block. The reply is
    coerced to a list (a stray single-object / fenced / prose-wrapped reply degrades gracefully)."""
    user_prompt = build_batch_user_prompt(batch, sources_map)
    system_text = load_analyst_prompt() + "\n\n" + BATCH_INSTRUCTION + "\n\n" + context_block
    messages = [
        {"role": "system", "content": system_text},
        {"role": "user", "content": user_prompt},
    ]

    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response, _used = llm.complete(messages, temperature=LLM_TEMPERATURE)
            raw = response.choices[0].message.content
            parsed = parse_json_list(raw)
            usage = getattr(response, "usage", None)
            t_in = getattr(usage, "prompt_tokens", 0) if usage else 0
            t_out = getattr(usage, "completion_tokens", 0) if usage else 0
            return parsed, t_in, t_out
        except (json.JSONDecodeError, Exception) as e:
            last_err = e
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)
    raise last_err


def analyze_one(article, context_block, sources_map, llm):
    """LLM call with retry. Returns (parsed_dict, tokens_in, tokens_out). `llm` is a ResilientLLM:
    each call is hard-bounded by a timeout and falls back to a second model if the primary is
    unreachable (2026-06-22 — a hung Gemini no longer leaves articles unscored / hangs the run)."""
    user_prompt = build_user_prompt(article, sources_map)
    system_text = load_analyst_prompt() + "\n\n" + context_block
    messages = [
        {"role": "system", "content": system_text},
        {"role": "user", "content": user_prompt},
    ]

    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response, _used = llm.complete(messages, temperature=LLM_TEMPERATURE)
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


# --- NF-ANALYST-SUB: route scoring through the flat Max subscription (claude -p) -------------
class _SubMsg:
    def __init__(self, content): self.message = type("M", (), {"content": content})()
class _SubUsage:
    def __init__(self, t_in, t_out):
        self.prompt_tokens = t_in
        self.completion_tokens = t_out
class _SubResponse:
    """Mimics the litellm response shape the analyst reads (choices[0].message.content + usage)."""
    def __init__(self, content, t_in, t_out):
        self.choices = [_SubMsg(content)]
        self.usage = _SubUsage(t_in, t_out)


class SubscriptionLLM:
    """Routes analyst scoring through `claude -p` (the flat Max subscription) and falls back to the
    wrapped API ResilientLLM on ANY failure — so the analyst can run $0-metered while never dropping a
    call. Exposes the surface run_analyst reads (fallback / timeout_s / used_fallback / effective_model)
    by proxying the API llm. Same .complete(messages, temperature) signature as ResilientLLM, so both
    analyze_one and analyze_batch use it unchanged."""
    def __init__(self, api_llm, model="haiku", timeout=600, max_thinking_tokens=0):
        self.api = api_llm
        self.model = model
        self.timeout = int(timeout)
        self.max_thinking_tokens = int(max_thinking_tokens)
        self.used_subscription = False
        self.used_api_fallback = False

    def complete(self, messages, temperature=None):
        system = "\n\n".join(m["content"] for m in messages if m.get("role") == "system")
        user = "\n\n".join(m["content"] for m in messages if m.get("role") == "user")
        try:
            text, _model_used, t_in, t_out = cc_writer.complete_via_subscription(
                system, user, model=self.model, timeout=self.timeout,
                max_thinking_tokens=self.max_thinking_tokens)
            self.used_subscription = True
            return _SubResponse(text, t_in, t_out), "subscription"
        except Exception as e:
            self.used_api_fallback = True
            print(f"  analyst SUBSCRIPTION failed ({type(e).__name__}: {str(e)[:120]}); API fallback")
            return self.api.complete(messages, temperature=temperature)

    @property
    def fallback(self):
        return self.api.fallback

    @property
    def timeout_s(self):
        return self.api.timeout_s

    @property
    def used_fallback(self):
        return bool(getattr(self.api, "used_fallback", False) or self.used_api_fallback)

    def effective_model(self):
        # An API fallback (even once) overrides; otherwise the subscription model. The
        # `subscription:` prefix makes run_analyst force cost=0 (flat plan, no metered $).
        if self.used_api_fallback:
            return self.api.effective_model()
        return f"subscription:{self.model}"


def maybe_wrap_subscription(api_llm, config):
    """If `analyst_use_subscription` is on, wrap the API llm so scoring runs via `claude -p` (flat Max
    plan) with an API fallback. Default off -> returns api_llm unchanged (today's API-only behaviour)."""
    if not bool(config.get("analyst_use_subscription", False)):
        return api_llm
    return SubscriptionLLM(
        api_llm,
        model=config.get("analyst_subscription_model", "haiku"),
        timeout=int(config.get("analyst_subscription_timeout_seconds", 600)),
        max_thinking_tokens=int(config.get("analyst_subscription_max_thinking_tokens", 0)),
    )


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
    topics = [str(t).lower()[:TOPIC_MAX_CHARS] for t in topics if t][:MAX_TOPICS]

    act = parsed.get("actionability")
    if not isinstance(act, int) or not (0 <= act <= 3):
        act = 0

    title = (article.get("title") or "").lower()
    branch = article.get("branch")
    has_breaking_kw = any(kw in title for kw in BREAKING_SIGNALS)

    if rel >= ACTIONABILITY_REL_THRESHOLD and branch == "IMMEDIATE" and act < 2:
        act = 2
    if has_breaking_kw and rel >= BREAKING_ACTIONABILITY_REL_THRESHOLD and act < 2:
        act = 2

    pi = parsed.get("perspective_invited")
    if not isinstance(pi, bool):
        pi = (rel >= PERSPECTIVE_REL_THRESHOLD and label in {"NEW_SIGNAL", "CONFIRMS_HYPOTHESIS", "CHALLENGES_HYPOTHESIS"})

    reasoning = str(parsed.get("reasoning", ""))[:REASONING_MAX_CHARS]
    differentiator = str(parsed.get("differentiator", ""))[:DIFFERENTIATOR_MAX_CHARS]

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


def score_articles(articles, context_block, sources_map, hypothesis_ids, llm, batch_size):
    """Score every article, BATCHED (batch_size articles per LLM call), with a per-article
    fallback for any article the batch omits OR a whole chunk whose batch call fails — so a
    batch slip can never silently drop articles from scoring (the data-loss guard). DB-free +
    llm-injected, so the routing is unit-testable.

    Returns (rows, failed_ids, total_in, total_out):
      rows       : list of (article, cleaned_dict) ready to insert
      failed_ids : article_ids that could not be scored even per-article (loud; retried next run)
    """
    rows = []
    failed_ids = []
    total = {"in": 0, "out": 0}

    def _score_one(article):
        try:
            parsed, t_in, t_out = analyze_one(article, context_block, sources_map, llm)
            total["in"] += t_in
            total["out"] += t_out
            rows.append((article, validate_and_clean(parsed, hypothesis_ids, article)))
        except Exception as e:
            print(f"  analyst per-article FAILED: {e} | {article.get('title','')[:60]}")
            failed_ids.append(article["id"])

    by_id = {a["id"]: a for a in articles}
    for i in range(0, len(articles), batch_size):
        chunk = articles[i:i + batch_size]
        try:
            parsed, t_in, t_out = analyze_batch(chunk, context_block, sources_map, llm)
            total["in"] += t_in
            total["out"] += t_out
            results_by_id, missing_ids = map_batch_results(chunk, parsed)
            for art in chunk:
                res = results_by_id.get(art["id"])
                if res is not None:
                    rows.append((art, validate_and_clean(res, hypothesis_ids, art)))
            for mid in missing_ids:   # the LLM omitted these — re-score each individually
                _score_one(by_id[mid])
        except Exception as e:
            print(f"  analyst batch FAILED ({len(chunk)} articles), falling back per-article: {e}")
            for art in chunk:
                _score_one(art)

    return rows, failed_ids, total["in"], total["out"]


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
    llm = resilient_from_config(config, "analyst_model", "analyst_fallback_model",
                                "anthropic/claude-haiku-4-5", label="analyst")
    llm = maybe_wrap_subscription(llm, config)   # NF-ANALYST-SUB: claude -p path if enabled (default off)
    cap = int(config.get("analyst_max_articles_per_run", 300))
    window_hours = int(config.get("analyst_window_hours", 30))
    batch_size = resolve_batch_size(config)
    start = time.time()

    print("NewsFramer Analyst starting...")
    print(f"  Model: {model} (fallback: {llm.fallback or 'none'}, timeout {int(llm.timeout_s)}s)  "
          f"|  Cap: {cap}  |  Batch: {batch_size}" + ("  (per-article)" if batch_size <= 1 else ""))
    if isinstance(llm, SubscriptionLLM):
        print(f"  Subscription: ON (claude -p, model={llm.model}, API fallback)")

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

    def _insert(article, cleaned):
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

    if batch_size > 1:
        # Batched path (NF-ANALYST-BATCH): ~len/batch_size LLM calls instead of one per article;
        # any article the batch omits / a failed chunk falls back to per-article (no data loss).
        rows, failed_ids, total_in, total_out = score_articles(
            articles, context_block, sources_map, hypothesis_ids, llm, batch_size)
        failed = len(failed_ids)
        for idx, (article, cleaned) in enumerate(rows, 1):
            try:
                _insert(article, cleaned)
                inserted += 1
                print(f"[{idx}/{len(rows)}] rel={cleaned['relevance_score']} "
                      f"label={cleaned['label']:22} act={cleaned['actionability']} "
                      f"hyps={len(cleaned['hypotheses'])} | {article['title'][:60]}")
            except Exception as e:
                failed += 1
                print(f"[insert {idx}] FAILED: {e} | {article.get('title','')[:60]}")
    else:
        # Per-article path — byte-for-byte the original behaviour (analyst_batch_size=1 = revert).
        for i, article in enumerate(articles, 1):
            try:
                parsed, t_in, t_out = analyze_one(article, context_block, sources_map, llm)
                total_in += t_in
                total_out += t_out
                cleaned = validate_and_clean(parsed, hypothesis_ids, article)
                _insert(article, cleaned)
                inserted += 1
                print(f"[{i}/{len(articles)}] rel={cleaned['relevance_score']} "
                      f"label={cleaned['label']:22} act={cleaned['actionability']} "
                      f"hyps={len(cleaned['hypotheses'])} | {article['title'][:60]}")
            except Exception as e:
                failed += 1
                print(f"[{i}/{len(articles)}] FAILED: {e} | {article.get('title','')[:60]}")
                continue

    used_model = llm.effective_model()   # the fallback if the breaker opened, else the primary
    duration_ms = int((time.time() - start) * 1000)
    # Subscription = flat Max plan, no metered $ (mirrors the writer); API path = estimate.
    cost = 0.0 if str(used_model).startswith("subscription") else estimate_cost(config, used_model, total_in, total_out)
    status = "success" if failed == 0 else "partial"
    err = f"{failed} article(s) failed" if failed else None
    if llm.used_fallback:   # observability: the primary provider was down this run
        err = (err + "; " if err else "") + f"primary unreachable — used fallback {used_model}"

    # Loud on silent data loss: skipped articles drop out of scoring entirely.
    if failed:
        print(f"  ALERT: analyst dropped {failed}/{len(articles)} article(s) "
              f"(unscored -> absent from the brief).")

    record_run(sb, {
        "agent_name": "analyst",
        "model_used": used_model,
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
