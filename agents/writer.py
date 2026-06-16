"""
OpenClaw Writer Agent
---------------------
Reads analyzed articles within the configured freshness window, groups them into themes,
generates a fact-organized briefing in the user's primary language, and stores it in `briefings`.

v1 scope: fact synthesis only, no original commentary.
Phase 2 will add post-draft generation in user voice.
"""

import os
import sys
import json
import time
import yaml
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from litellm import completion
from supabase import create_client
from dotenv import load_dotenv

# writer.py runs BOTH as a script (python agents/writer.py, agents/ on sys.path[0])
# and as an imported module (run_whatsapp_brief.py does `from agents.writer import ...`,
# with only the repo root on the path). Put this file's own dir on the path so the
# sibling helpers below resolve in BOTH cases.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from run_log import record_run  # noqa: E402
from llm_json import parse_json_obj  # noqa: E402
from drop_reports import (  # noqa: E402
    make_slug, is_woven, render_investigations_section, splice_investigations, pick_diverse,
)
from bundle_floors import select_themes_with_floors  # noqa: E402
from char_monitor import overrun_flag  # noqa: E402  (NF-F2: over-cap quality flag)
from source_skew import skew_warning, coverage_note  # noqa: E402  (NF-D3 skew flag + NF-NEW10c one-sided note)

load_dotenv()

try:  # Windows consoles default to cp1252 and crash printing 🔍 / non-latin glyphs.
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# Asia/Tokyo (JST = UTC+9, no DST). The brief date/header must be JST, not UTC: a 06:00 JST
# run is 21:00 UTC the prior day, so a UTC date would show YESTERDAY.
JST = timezone(timedelta(hours=9))


def load_config():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(base_dir, "config", "models.yaml"), "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# --- Tunables (sourced from config; defaults reproduce prior behaviour). See config/models.yaml. ---
try:
    _CFG = load_config()
except Exception:
    _CFG = {}
THEME_SNIPPET_CHARS = int(_CFG.get("writer_theme_snippet_chars", 600))
HIGHLIGHT_SNIPPET_CHARS = int(_CFG.get("writer_highlight_snippet_chars", 400))
DROP_CONTENT_CHARS = int(_CFG.get("drop_report_content_chars", 3000))
DROP_TEMPERATURE = float(_CFG.get("drop_report_temperature", 0.2))
DROP_MAX_TOKENS = int(_CFG.get("drop_report_max_tokens", 900))
DROP_SHORT_MAX_CHARS = int(_CFG.get("drop_report_short_max_chars", 400))
DROP_LONG_MAX_CHARS = int(_CFG.get("drop_report_long_max_chars", 2000))


def load_prompt_files():
    """Load the four prompt files. User edits these to customize Writer behavior."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    prompts_dir = os.path.join(base_dir, "prompts", "writer")
    parts = []
    for fname in ["system_prompt.txt", "tone.txt", "format_rules.txt"]:
        path = os.path.join(prompts_dir, fname)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                parts.append(f.read().strip())
        else:
            print(f"  WARN: prompt file missing: {path}")
    return "\n\n".join(parts)


def get_supabase():
    return create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_KEY"))


def load_user_context(sb):
    r = (
        sb.table("user_context")
        .select("id, topic, stance, reasoning, confidence, kind, weight")
        .eq("active", True)
        .execute()
    )
    rows = r.data or []
    interests = [row for row in rows if row.get("kind") == "interest"]
    hypotheses = [
        row for row in rows
        if row.get("kind") == "hypothesis"
        and row.get("status") in ("active", "partially_confirmed", "pending_confirmation")
    ]
    by_id = {row["id"]: row for row in rows}
    return {"interests": interests, "hypotheses": hypotheses, "by_id": by_id}


def load_window_scored_articles(sb, window_hours, exclude_account=None):
    """All fresh, alive, analyst-scored articles in the window, MINUS any already
    delivered to `exclude_account` (§4.3 set-difference). The relevance threshold /
    backoff is applied by the caller, not here. Returns (articles_with_score,
    total_in_window). Window-first + paged + chunked to avoid PostgREST's 1000-row cap.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=window_hours)).isoformat()

    # 1. Fresh, alive articles in the window (paged).
    arts = []
    PAGE = 1000
    start = 0
    while True:
        r = (
            sb.table("raw_articles")
            .select("id, source_id, title, url, content_raw, published_at")
            .gte("published_at", cutoff)
            .is_("deleted_at", "null")
            .order("published_at", desc=True)
            .range(start, start + PAGE - 1)
            .execute()
        )
        batch = r.data or []
        arts.extend(batch)
        if len(batch) < PAGE:
            break
        start += PAGE
    total_in_window = len(arts)
    if not arts:
        return [], 0

    window_ids = [a["id"] for a in arts]

    # 2. §4.3 set-difference: which of these were already delivered to this account?
    #    Scoped to the window ids (chunked) so it can't hit the 1000-row cap.
    delivered = set()
    if exclude_account:
        for i in range(0, len(window_ids), 50):
            chunk = window_ids[i:i + 50]
            d = (
                sb.table("deliveries")
                .select("article_id")
                .eq("account", exclude_account)
                .in_("article_id", chunk)
                .execute()
            )
            for row in (d.data or []):
                if row.get("article_id"):
                    delivered.add(row["article_id"])

    # 3. Scores for the non-delivered in-window articles (chunked).
    candidate_ids = [i for i in window_ids if i not in delivered]
    scores_by_article = {}
    for i in range(0, len(candidate_ids), 50):
        ids_chunk = candidate_ids[i:i + 50]
        r2 = (
            sb.table("analyst_scores")
            .select(
                "article_id, relevance_score, label, hypotheses, topics, actionability, "
                "perspective_invited, reasoning, differentiator"
            )
            .in_("article_id", ids_chunk)
            .execute()
        )
        for row in (r2.data or []):
            scores_by_article[row["article_id"]] = row

    # 4. Attach scores; keep only scored, non-delivered articles. No threshold here.
    out = []
    for a in arts:
        if a["id"] in delivered:
            continue
        s = scores_by_article.get(a["id"])
        if s:
            a["score"] = s
            out.append(a)
    return out, total_in_window


def load_sources_map(sb):
    r = sb.table("sources").select("id, name").execute()
    return {s["id"]: s.get("name", "Unknown") for s in (r.data or [])}


def load_source_categories(sb):
    """source_id -> category (the 'bundle' an article belongs to, spec §8.1)."""
    r = sb.table("sources").select("id, category").execute()
    return {s["id"]: s.get("category") for s in (r.data or [])}


def composite_score(article):
    """Combined ranking score."""
    s = article["score"]
    rel = s.get("relevance_score") or 0
    act = s.get("actionability") or 0
    return rel * 10 + act * 15


def cluster_by_topic_overlap(articles, max_themes, max_per_theme):
    """Greedy clustering by shared topic tags. Returns (clusters, leftovers).
    Clusters: list of article-lists, sorted by total composite score, capped at max_themes.
    Leftovers: articles that did NOT make it into the returned clusters.
    """
    ordered = sorted(articles, key=composite_score, reverse=True)

    all_clusters = []
    used_ids = set()

    for seed in ordered:
        if seed["id"] in used_ids:
            continue
        seed_topics = set(seed["score"].get("topics") or [])
        if not seed_topics:
            all_clusters.append([seed])
            used_ids.add(seed["id"])
            continue

        cluster = [seed]
        used_ids.add(seed["id"])

        for other in ordered:
            if other["id"] in used_ids:
                continue
            if len(cluster) >= max_per_theme:
                break
            other_topics = set(other["score"].get("topics") or [])
            shared = seed_topics & other_topics
            if len(shared) >= 2 or (len(shared) >= 1 and (len(seed_topics) <= 2 or len(other_topics) <= 2)):
                cluster.append(other)
                used_ids.add(other["id"])

        all_clusters.append(cluster)

    # Rank by composite sum
    all_clusters.sort(key=lambda c: sum(composite_score(a) for a in c), reverse=True)

    # Top max_themes become themes
    themes = all_clusters[:max_themes]
    theme_article_ids = {a["id"] for cluster in themes for a in cluster}

    # Everything else is leftover candidates for highlights
    leftovers = [a for a in articles if a["id"] not in theme_article_ids]

    return themes, leftovers


def pick_highlights(leftovers, count, min_relevance):
    """Select top-N highest-relevance singleton articles from leftovers."""
    eligible = [a for a in leftovers if (a["score"].get("relevance_score") or 0) >= min_relevance]
    eligible.sort(key=composite_score, reverse=True)
    return eligible[:count]


def build_context_block(context):
    """Mirror of Analyst's logic but read-only context for Writer."""
    interests = context.get("interests", [])
    hypotheses = context.get("hypotheses", [])
    lines = []

    lines.append("USER INTERESTS (use to prioritize themes; do not editorialize):")
    if not interests:
        lines.append("(none specified)")
    else:
        for it in interests:
            w = it.get("weight")
            w_str = f"{w:+d}" if isinstance(w, int) else "0"
            lines.append(f"- topic='{it.get('topic','')}' weight={w_str}")
    lines.append("")

    lines.append("ACTIVE HYPOTHESES (surface when articles relate, factually):")
    if not hypotheses:
        lines.append("(none active)")
    else:
        for h in hypotheses:
            lines.append(
                f"- id={h['id']} | topic={h.get('topic','')} | stance={h.get('stance','')}"
            )
    return "\n".join(lines)


def build_articles_block(clusters, sources_map, by_hypothesis_id, coverage_notes=None):
    """Format clusters as structured input for Writer LLM. coverage_notes (NF-NEW10c,
    optional) is a list aligned with clusters; 'left'/'right' marks a one-sided theme so the
    LLM appends the media-only warning to exactly that section."""
    lines = ["CLUSTERED ARTICLES (each cluster becomes one theme):"]
    for i, cluster in enumerate(clusters, 1):
        note = (coverage_notes[i - 1] if coverage_notes and i - 1 < len(coverage_notes) else None)
        tag = f" [ONE-SIDED COVERAGE: {note}]" if note in ("left", "right") else ""
        lines.append(f"\n=== Cluster {i} ({len(cluster)} articles){tag} ===")
        for a in cluster:
            s = a["score"]
            src_name = sources_map.get(a.get("source_id"), "Unknown")
            hyps = s.get("hypotheses") or []
            hyp_strs = []
            for h in hyps:
                hid = h.get("id")
                align = h.get("alignment")
                meta = by_hypothesis_id.get(hid)
                if meta:
                    hyp_strs.append(
                        f"matches hypothesis '{meta.get('topic')}' "
                        f"(stance={meta.get('stance')}) alignment={align:+d}"
                    )
            hyp_str = "; ".join(hyp_strs) if hyp_strs else "none"

            lines.append(
                f"\nArticle:\n"
                f"  url: {a.get('url','')}\n"
                f"  source: {src_name}\n"
                f"  title: {a.get('title','')}\n"
                f"  published_at: {a.get('published_at','')}\n"
                f"  relevance: {s.get('relevance_score')}\n"
                f"  actionability: {s.get('actionability')}\n"
                f"  topics: {', '.join(s.get('topics') or [])}\n"
                f"  differentiator: {s.get('differentiator','') or '(none)'}\n"
                f"  analyst_reasoning: {s.get('reasoning','') or '(none)'}\n"
                f"  hypothesis_matches: {hyp_str}\n"
                f"  perspective_invited: {s.get('perspective_invited')}\n"
                f"  content_snippet: {(a.get('content_raw') or '')[:THEME_SNIPPET_CHARS].replace(chr(10), ' ')}"
            )
    return "\n".join(lines)


def build_highlights_block(highlights, sources_map):
    if not highlights:
        return "HIGHLIGHTS (none qualifying — omit the ## Highlights section entirely):"
    lines = ["HIGHLIGHTS (each becomes one bullet in the ## Highlights section):"]
    for h in highlights:
        s = h["score"]
        src_name = sources_map.get(h.get("source_id"), "Unknown")
        lines.append(
            f"\nHighlight:\n"
            f"  url: {h.get('url','')}\n"
            f"  source: {src_name}\n"
            f"  title: {h.get('title','')}\n"
            f"  relevance: {s.get('relevance_score')}\n"
            f"  topics: {', '.join(s.get('topics') or [])}\n"
            f"  differentiator: {s.get('differentiator','') or '(none)'}\n"
            f"  analyst_reasoning: {s.get('reasoning','') or '(none)'}\n"
            f"  content_snippet: {(h.get('content_raw') or '')[:HIGHLIGHT_SNIPPET_CHARS].replace(chr(10), ' ')}"
        )
    return "\n".join(lines)


def build_user_prompt(clusters, highlights, sources_map, by_hypothesis_id, context,
                     total_in_window, relevant_count, briefing_date, max_chars, coverage_notes=None):
    context_block = build_context_block(context)
    articles_block = build_articles_block(clusters, sources_map, by_hypothesis_id, coverage_notes)
    highlights_block = build_highlights_block(highlights, sources_map)
    theme_count = len(clusters)
    highlight_count = len(highlights)

    instructions = (
        f"\n\nGenerate the briefing now.\n"
        f"- Date for header: {briefing_date}\n"
        f"- Number of themes: {theme_count}\n"
        f"- Number of highlights: {highlight_count}\n"
        f"- Articles total in window: {total_in_window}\n"
        f"- Articles meeting relevance cutoff: {relevant_count}\n"
        f"- Hard character limit: {max_chars}\n"
        f"- Footer must use these exact numbers in this format:\n"
        f"  ---\n"
        f"  _Briefing generated from {total_in_window} articles. {relevant_count} made the relevance cutoff. {theme_count} themes, {highlight_count} highlights._\n"
        f"- If highlights count is 0, OMIT the ## Highlights section entirely.\n"
        f"- One-sided coverage (NF-NEW10c): if a cluster header is marked "
        f"'[ONE-SIDED COVERAGE: left]', make the FINAL line of that theme's section exactly "
        f"'_⚠ Left-leaning media only — opposing view absent._'; for "
        f"'[ONE-SIDED COVERAGE: right]' use "
        f"'_⚠ Right-leaning media only — opposing view absent._'. Add nothing for "
        f"clusters without that marker.\n"
        f"- Output ONLY the Markdown briefing. No preamble, no postamble.\n"
    )

    return f"{context_block}\n\n{articles_block}\n\n{highlights_block}\n{instructions}"


def estimate_cost(config, model, tokens_in, tokens_out):
    pricing = (config.get("pricing") or {}).get(model)
    if not pricing:
        return 0.0
    return (tokens_in / 1_000_000) * pricing["input"] + (tokens_out / 1_000_000) * pricing["output"]


def _log_writer_skip(sb, reason, total_in_window):
    """Record a no-brief outcome so a quiet/missed run is observable (the delivery layer alerts)."""
    try:
        sb.table("agent_runs").insert(
            {"agent_name": "writer", "model_used": "none", "status": reason}
        ).execute()
    except Exception as e:
        print(f"  (could not log writer skip: {e})")
    print(f"  Writer skip logged: {reason} (in-window={total_in_window})")


# --- Drop-reports (spec 8.5, basic). Telegram-self path only; WhatsApp untouched. ---
DROP_SUMMARY_SYSTEM = (
    "You summarize an investigative-journalism / OSINT report for a personal news brief.\n"
    'Return ONLY a JSON object: {"short": "...", "long": "..."}.\n'
    "- short: ONE factual sentence, <= 280 characters, no hype, no speculation.\n"
    "- long: 2-4 short paragraphs, <= 1200 characters: what the investigation found, the "
    "method/evidence, who is involved, and why it matters.\n"
    "Use ONLY facts in the provided article. No markdown fences, no commentary outside the JSON."
)


def load_investigative_ids(sb):
    """Source ids whose category is 'investigative' (the drop-report sources, spec 8.5)."""
    r = sb.table("sources").select("id").eq("category", "investigative").execute()
    return {row["id"] for row in (r.data or [])}


def load_drop_report_candidates(sb, window_hours, investigative_ids, exclude_account=None):
    """Scored, non-delivered articles from investigative sources within a wider
    (7-day) window. Mirrors load_window_scored_articles but scoped to drop sources,
    so low-frequency investigative drops actually surface (spec 8.5; §4.3 dedup)."""
    if not investigative_ids:
        return []
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=window_hours)).isoformat()
    inv = list(investigative_ids)
    arts = []
    for i in range(0, len(inv), 50):
        chunk = inv[i:i + 50]
        start = 0
        while True:
            r = (
                sb.table("raw_articles")
                .select("id, source_id, title, url, content_raw, published_at")
                .in_("source_id", chunk)
                .gte("published_at", cutoff)
                .is_("deleted_at", "null")
                .order("published_at", desc=True)
                .range(start, start + 999)
                .execute()
            )
            batch = r.data or []
            arts.extend(batch)
            if len(batch) < 1000:
                break
            start += 1000
    if not arts:
        return []
    ids = [a["id"] for a in arts]
    delivered = set()
    if exclude_account:
        for i in range(0, len(ids), 50):
            d = (
                sb.table("deliveries").select("article_id")
                .eq("account", exclude_account).in_("article_id", ids[i:i + 50]).execute()
            )
            for row in (d.data or []):
                if row.get("article_id"):
                    delivered.add(row["article_id"])
    cand_ids = [i for i in ids if i not in delivered]
    scores = {}
    for i in range(0, len(cand_ids), 50):
        r2 = (
            sb.table("analyst_scores")
            .select("article_id, relevance_score, label, hypotheses, topics, actionability, "
                    "perspective_invited, reasoning, differentiator")
            .in_("article_id", cand_ids[i:i + 50]).execute()
        )
        for row in (r2.data or []):
            scores[row["article_id"]] = row
    out = []
    for a in arts:
        if a["id"] in delivered:
            continue
        s = scores.get(a["id"])
        if s:
            a["score"] = s
            out.append(a)
    return out


def generate_drop_summary(article, model, completion_fn=completion):
    """One cheap-model call -> {'short','long'} for a drop-report. Robust JSON parse;
    injectable completion_fn so the dry run can stub it (no LLM spend)."""
    content = (article.get("content_raw") or "")[:DROP_CONTENT_CHARS]
    user = (
        f"title: {article.get('title','')}\n"
        f"source_url: {article.get('url','')}\n"
        f"content:\n{content}"
    )
    resp = completion_fn(
        model=model,
        messages=[{"role": "system", "content": DROP_SUMMARY_SYSTEM},
                  {"role": "user", "content": user}],
        temperature=DROP_TEMPERATURE, max_tokens=DROP_MAX_TOKENS,
    )
    parsed = parse_json_obj(resp.choices[0].message.content)
    return {
        "short": str(parsed.get("short") or "").strip()[:DROP_SHORT_MAX_CHARS],
        "long": str(parsed.get("long") or "").strip()[:DROP_LONG_MAX_CHARS],
    }


def build_drops(drop_candidates, main_theme_topics, max_drops, model, sources_map,
                completion_fn=completion, max_per_source=1):
    """Pick the top drops, weave-flag each against the main theme, and generate
    summaries. Returns dicts {article, render, store, woven}. Logs if more than
    max_drops qualify (no silent cap). On a summary failure, falls back to the
    analyst's own text rather than crashing the brief."""
    ordered = sorted(drop_candidates, key=composite_score, reverse=True)
    if len(ordered) > max_drops:
        print(f"  DROP CAP: {len(ordered)} investigative articles qualified; keeping top {max_drops} "
              f"(others wait for a later brief).")
    chosen = pick_diverse(ordered, max_drops, max_per_source, lambda a: a.get("source_id"))
    slugs = set()
    out = []
    for a in chosen:
        topics = a["score"].get("topics") or []
        woven = is_woven(topics, main_theme_topics)
        slug = make_slug(a.get("title", ""), slugs)
        slugs.add(slug)
        source = sources_map.get(a.get("source_id"), "Unknown")
        try:
            summary = generate_drop_summary(a, model, completion_fn)
        except Exception as e:
            print(f"  WARN: drop summary failed for '{a.get('title','')[:50]}': {e}; using analyst text.")
            s = a["score"]
            summary = {
                "short": (s.get("differentiator") or s.get("reasoning") or a.get("title", ""))[:280],
                "long": (s.get("reasoning") or "")[:1200],
            }
        render = {"title": a.get("title", ""), "short": summary["short"],
                  "source": source, "url": a.get("url", ""), "slug": slug}
        store = {**render, "long": summary["long"], "woven": woven,
                 "article_id": a["id"], "topics": topics}
        out.append({"article": a, "render": render, "store": store, "woven": woven})
    return out


def persist_drop_reports(date_str, drop_store_list, base_dir, briefing_id=None):
    """Write the day's drop reports to a local JSON store so the OpenClaw agent can
    return the long form on 'more: <slug>'. Best-effort; never sinks the brief."""
    try:
        d = os.path.join(base_dir, "data", "drop_reports")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, f"{date_str}.json")
        payload = {"date": date_str, "briefing_id": briefing_id, "drops": drop_store_list}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"  Drop-reports stored: {path} ({len(drop_store_list)} drop(s))")
        return path
    except Exception as e:
        print(f"  WARN: could not persist drop reports (non-fatal): {e}")
        return None


def run_writer():
    config = load_config()
    sb = get_supabase()
    start = time.time()

    model = config.get("writer_model", "anthropic/claude-haiku-4-5")
    lang = config.get("writer_primary_language", "en")
    min_rel = int(config.get("writer_min_relevance", 6))
    rel_floor = int(config.get("writer_relevance_floor", 4))
    delivery_account = config.get("writer_delivery_account", "newsframer")
    min_themes = int(config.get("writer_min_themes", 3))
    max_per_theme = int(config.get("writer_max_articles_per_theme", 6))
    window_hours = int(config.get("writer_window_hours", 24))
    # Fix 2: char cap scales with the number of themes (computed after clustering, below).
    per_theme_chars = int(config.get("writer_per_theme_chars", 2500))
    max_chars_floor = int(config.get("writer_max_chars_floor", 6000))
    max_chars_ceiling = int(config.get("writer_max_chars_ceiling", 16000))
    # Per-bundle theme floors (spec §8.1/§8.6) — Telegram brief only. Guarantee each active
    # bundle a floor of themes, cap any single bundle, scale total with active-bundle count.
    bundle_floors = config.get("bundle_theme_floors") or {
        "crypto": 1, "geopolitics": 1, "pakistan": 1, "cybersecurity": 1, "tech": 1
    }
    bundle_cap = int(config.get("bundle_theme_cap", 2))
    theme_multiplier = float(config.get("theme_count_multiplier", 1.5))
    theme_total_max = int(config.get("theme_count_max", 10))
    writer_temperature = float(config.get("writer_temperature", 0.3))
    writer_max_tokens = int(config.get("writer_max_tokens", 4500))

    print("OpenClaw Writer starting...")
    print(f"  Model:          {model}")
    print(f"  Language:       {lang}")
    print(f"  Window:         {window_hours}h")
    print(f"  Min relevance:  {min_rel} (floor {rel_floor})")
    print(f"  Themes:         min {min_themes}, per-bundle floors (cap {bundle_cap}, x{theme_multiplier}, max {theme_total_max})")
    print(f"  Char budget:    {per_theme_chars}/theme (floor {max_chars_floor}, ceiling {max_chars_ceiling})")

    context = load_user_context(sb)
    print(f"  Interests:      {len(context['interests'])}")
    print(f"  Hypotheses:     {len(context['hypotheses'])}")

    candidates, total_in_window = load_window_scored_articles(
        sb, window_hours, exclude_account=delivery_account
    )
    sources_map = load_sources_map(sb)

    # Drop-reports (spec 8.5): investigative-category sources are handled on a wider
    # 7-day deduped window, never as plain highlights. Pull them OUT of the normal
    # 24h pool first so nothing double-lists. No investigative sources -> all no-ops.
    investigative_ids = load_investigative_ids(sb)
    if investigative_ids:
        before = len(candidates)
        candidates = [a for a in candidates if a.get("source_id") not in investigative_ids]
        if before != len(candidates):
            print(f"  Drop sources: pulled {before - len(candidates)} investigative article(s) "
                  f"from the normal pool (handled as drops).")
    drop_window = int(config.get("drop_report_window_hours", 168))
    drop_candidates = load_drop_report_candidates(
        sb, drop_window, investigative_ids, exclude_account=delivery_account
    )
    print(f"  Drop-report candidates (investigative, {drop_window}h, non-delivered): {len(drop_candidates)}")

    # §4.5 relevance backoff: lower the threshold ONLY within the 24h window (never outside),
    # down to writer_relevance_floor, until at least min_themes articles qualify.
    def _over_bar(a, rel):
        s = a["score"]
        return (s.get("relevance_score") or 0) >= rel or (s.get("actionability") or 0) >= 2

    articles = []
    chosen_rel = min_rel
    for rel in range(min_rel, rel_floor - 1, -1):
        chosen_rel = rel
        articles = [a for a in candidates if _over_bar(a, rel)]
        if len(articles) >= min_themes:
            break

    print(f"  Articles in {window_hours}h window:  {total_in_window}")
    print(f"  Non-delivered scored:       {len(candidates)}")
    print(f"  Qualifying (rel>={chosen_rel} or act>=2): {len(articles)}\n")

    # §4.5 thin-day guard. Never backfill older/lower than the floor.
    quiet_day = False
    if len(articles) < min_themes:
        if len(articles) >= 1:
            quiet_day = True
            print(f"  THIN DAY: {len(articles)} qualify (< {min_themes}). Writing a short quiet-day brief.")
        else:
            print("  QUIET DAY: 0 articles qualified within 24h. No brief written (delivery layer will alert).")
            _log_writer_skip(sb, "quiet_day_no_articles", total_in_window)
            return

    effective_min_themes = 1 if quiet_day else min_themes

    # Per-bundle theme floors (spec §8.1/§8.6): cluster ALL qualifying articles (the clustering
    # algorithm is unchanged — passing a large cap just makes it return every cluster instead of
    # pre-truncating to the top-N), then re-allocate which clusters become themes so each active
    # bundle gets its floor, no bundle exceeds its cap, and the total scales with the active-bundle
    # count. Telegram brief only; WhatsApp (which reuses cluster_by_topic_overlap directly) is untouched.
    all_clusters, _ = cluster_by_topic_overlap(articles, len(articles), max_per_theme)
    source_categories = load_source_categories(sb)
    clusters, leftovers, floor_report = select_themes_with_floors(
        all_clusters, source_categories, bundle_floors, bundle_cap, theme_multiplier, theme_total_max
    )
    print(f"  Bundle floors: {floor_report['num_active']} active bundle(s) -> "
          f"{floor_report['theme_count']}/{floor_report['target_total']} themes | "
          f"by-score={floor_report['before']} floored={floor_report['after']}")
    # NF-D3: log-only source-skew flag per theme (uses the NF-D1 Ground-News bias tags).
    # Fully wrapped — a bias-data hiccup just skips the check; it NEVER alters the brief.
    _bias_of = {}
    try:
        _bias_rows = sb.table("sources").select("id, groundnews_publication_bias").execute().data or []
        _bias_of = {r["id"]: r.get("groundnews_publication_bias") for r in _bias_rows}
        for _i, _c in enumerate(clusters, 1):
            _w = skew_warning([(a.get("source_id"), _bias_of.get(a.get("source_id"))) for a in _c])
            if _w:
                print(f"  ⚠ THEME {_i} SOURCE-SKEW: {_w}")
    except Exception as _e:
        print(f"  (source-skew check skipped: {type(_e).__name__})")
    highlights_count = int(config.get("writer_highlights_count", 8))
    highlights_min_rel = int(config.get("writer_highlights_min_relevance", 8))
    highlights = pick_highlights(leftovers, highlights_count, highlights_min_rel)

    print(f"  Clusters formed: {len(clusters)}\n")
    for i, c in enumerate(clusters, 1):
        print(f"  Cluster {i}: {len(c)} articles, top: '{c[0]['title'][:70]}'")
    print(f"\n  Highlights selected: {len(highlights)}")
    for h in highlights:
        print(f"    rel={h['score'].get('relevance_score')} | {h['title'][:70]}")

    if len(clusters) < effective_min_themes:
        print(f"\nOnly {len(clusters)} clusters. Need {effective_min_themes}+. Briefing skipped.")
        _log_writer_skip(sb, "no_clusters", total_in_window)
        return

    # Drop-reports: weave-flag each against the main theme (themes[0]) and generate
    # short+long summaries (eager). Woven drops are added into the main theme cluster
    # so the LLM synthesizes them in; ALL drops also render in the Investigations
    # section below. Empty drop_candidates -> brief identical to today's.
    drop_model = config.get("drop_report_model", "gemini/gemini-2.5-flash-lite")
    drop_max = int(config.get("drop_report_max", 3))
    main_theme_topics = set()
    if clusters:
        for a in clusters[0]:
            main_theme_topics |= set(a["score"].get("topics") or [])
    drop_max_per_source = int(config.get("drop_report_max_per_source", 1))
    drops = build_drops(drop_candidates, main_theme_topics, drop_max, drop_model, sources_map,
                        max_per_source=drop_max_per_source) \
        if drop_candidates else []
    if drops:
        woven_n = sum(1 for d in drops if d["woven"])
        print(f"  Drops: {len(drops)} ({woven_n} woven into main theme, {len(drops) - woven_n} standalone)")
        for d in drops:
            if d["woven"] and clusters:
                clusters[0].append(d["article"])

    # Fix 2: cap scales with the themes the brief actually produces, clamped floor..ceiling.
    max_chars = max(max_chars_floor, min(max_chars_ceiling, per_theme_chars * len(clusters)))
    print(f"  Char cap: {per_theme_chars} x {len(clusters)} themes = {per_theme_chars * len(clusters)} "
          f"-> {max_chars} (floor {max_chars_floor}, ceiling {max_chars_ceiling})")

    now_jst = datetime.now(JST)
    briefing_date = now_jst.strftime("%Y-%m-%d (%H:%M JST)")
    system_prompt = load_prompt_files()
    relevant_count = len(articles)
    # NF-NEW10c: per-theme one-sided-coverage note (left/right media only), reflecting the FINAL
    # clusters (incl. woven drops). Wrapped — a hiccup just yields no notes; never breaks the brief.
    try:
        theme_coverage = [coverage_note([(a.get("source_id"), _bias_of.get(a.get("source_id"))) for a in c])
                          for c in clusters]
        _onesided = sum(1 for n in theme_coverage if n)
        if _onesided:
            print(f"  NF-NEW10c: {_onesided} theme(s) flagged one-sided (left/right media only)")
    except Exception as _e:
        theme_coverage = []
    user_prompt = build_user_prompt(
        clusters, highlights, sources_map, context["by_id"], context,
        total_in_window, relevant_count, briefing_date, max_chars, coverage_notes=theme_coverage
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    # Anthropic primary, Gemini 2.5 Flash-Lite fallback: an outage / rate-limit / billing
    # error on the primary degrades to the cheap model instead of failing the brief.
    fallback_model = config.get("writer_fallback_model", "gemini/gemini-2.5-flash-lite")
    used_model = model
    print(f"\nGenerating briefing with {model}...")
    try:
        response = completion(model=model, messages=messages, temperature=writer_temperature, max_tokens=writer_max_tokens)
    except Exception as primary_err:
        if fallback_model and fallback_model != model:
            print(f"  PRIMARY {model} FAILED: {primary_err}\n  Falling back to {fallback_model}...")
            used_model = fallback_model
            response = completion(model=used_model, messages=messages, temperature=writer_temperature, max_tokens=writer_max_tokens)
        else:
            raise
    briefing_text = response.choices[0].message.content.strip()
    if quiet_day:
        briefing_text = "_Quiet news day — fewer items than usual._\n\n" + briefing_text

    # Splice the deterministic Investigations section (drops always surface here,
    # whether or not they were also woven into the main theme). No drops -> no-op.
    briefing_text = splice_investigations(
        briefing_text, render_investigations_section([d["render"] for d in drops])
    )

    usage = getattr(response, "usage", None)
    t_in = getattr(usage, "prompt_tokens", 0) if usage else 0
    t_out = getattr(usage, "completion_tokens", 0) if usage else 0
    cost = estimate_cost(config, used_model, t_in, t_out)
    duration_ms = int((time.time() - start) * 1000)

    print(f"\n{'-' * 60}")
    print(briefing_text)
    print(f"{'-' * 60}\n")
    print(f"Briefing chars: {len(briefing_text)} (limit: {max_chars}) | model: {used_model}")
    # NF-F2: flag (don't fail) an over-cap brief so editorial drift is visible in the run log.
    _overrun = overrun_flag(len(briefing_text), max_chars,
                            config.get("writer_char_overrun_warn_ratio", 1.0))
    if _overrun:
        print(_overrun)
    print(f"Tokens: in={t_in} out={t_out} | Cost: ${cost:.4f} | Time: {duration_ms}ms")

    # Store. Record which article IDs went into the brief (clusters + highlights) so the
    # delivery layer can mark them delivered (§4.3) once the send is confirmed.
    selected_ids = (
        [a["id"] for cluster in clusters for a in cluster]
        + [h["id"] for h in highlights]
        + [d["article"]["id"] for d in drops]
    )
    selected_ids = list(dict.fromkeys(selected_ids))
    content_col = f"content_{lang}"
    insert_row = {
        "date": now_jst.date().isoformat(),
        content_col: briefing_text,
        "model_writer": used_model,
        "cost_usd": round(cost, 6),
        "article_ids": selected_ids,
    }
    result = sb.table("briefings").insert(insert_row).execute()
    briefing_id = result.data[0]["id"] if result.data else None
    print(f"Saved briefing id={briefing_id} ({len(selected_ids)} article_ids)")

    if drops:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        persist_drop_reports(
            now_jst.date().isoformat(), [d["store"] for d in drops], base_dir, briefing_id
        )

    record_run(sb, {
        "agent_name": "writer",
        "model_used": used_model,
        "tokens_in": t_in,
        "tokens_out": t_out,
        "cost_usd": round(cost, 6),
        "duration_ms": duration_ms,
        "status": "success",
    })


if __name__ == "__main__":
    run_writer()