"""
OpenClaw Writer Agent
---------------------
Reads analyzed articles within the configured freshness window, groups them into themes,
generates a fact-organized briefing in the user's primary language, and stores it in `briefings`.

v1 scope: fact synthesis only, no original commentary.
Phase 2 will add post-draft generation in user voice.
"""

import os
import time
import yaml
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from litellm import completion
from supabase import create_client
from dotenv import load_dotenv

load_dotenv()


def load_config():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(base_dir, "config", "models.yaml"), "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


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


def load_recent_analyzed_articles(sb, window_hours, min_relevance):
    """Articles with analyst_scores, fresh, alive, above relevance threshold."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=window_hours)).isoformat()

    # Articles qualify if EITHER relevance >= min OR actionability >= 2.
    # Bypass lets time-sensitive low-relevance stories surface.
    r = (
        sb.table("analyst_scores")
        .select(
            "article_id, relevance_score, label, hypotheses, topics, actionability, "
            "perspective_invited, reasoning, differentiator"
        )
        .or_(f"relevance_score.gte.{min_relevance},actionability.gte.2")
        .execute()
    )
    scores_by_article = {row["article_id"]: row for row in (r.data or [])}
    if not scores_by_article:
        return [], 0

    art_ids = list(scores_by_article.keys())

    # Fetch the articles, in chunks to avoid URL length issues
    all_arts = []
    CHUNK = 50
    for i in range(0, len(art_ids), CHUNK):
        ids_chunk = art_ids[i:i+CHUNK]
        r2 = (
            sb.table("raw_articles")
            .select("id, source_id, title, url, content_raw, published_at")
            .in_("id", ids_chunk)
            .gte("published_at", cutoff)
            .is_("deleted_at", "null")
            .execute()
        )
        all_arts.extend(r2.data or [])

    # Also count total analyzed in window (for footer)
    r3 = (
        sb.table("raw_articles")
        .select("id", count="exact")
        .gte("published_at", cutoff)
        .is_("deleted_at", "null")
        .execute()
    )
    total_in_window = r3.count or 0

    # Join score data into each article
    merged = []
    for a in all_arts:
        s = scores_by_article.get(a["id"])
        if s:
            a["score"] = s
            merged.append(a)
    return merged, total_in_window


def load_sources_map(sb):
    r = sb.table("sources").select("id, name").execute()
    return {s["id"]: s.get("name", "Unknown") for s in (r.data or [])}


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


def build_articles_block(clusters, sources_map, by_hypothesis_id):
    """Format clusters as structured input for Writer LLM."""
    lines = ["CLUSTERED ARTICLES (each cluster becomes one theme):"]
    for i, cluster in enumerate(clusters, 1):
        lines.append(f"\n=== Cluster {i} ({len(cluster)} articles) ===")
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
                f"  content_snippet: {(a.get('content_raw') or '')[:600].replace(chr(10), ' ')}"
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
            f"  content_snippet: {(h.get('content_raw') or '')[:400].replace(chr(10), ' ')}"
        )
    return "\n".join(lines)


def build_user_prompt(clusters, highlights, sources_map, by_hypothesis_id, context,
                     total_in_window, relevant_count, briefing_date, max_chars):
    context_block = build_context_block(context)
    articles_block = build_articles_block(clusters, sources_map, by_hypothesis_id)
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
        f"- Output ONLY the Markdown briefing. No preamble, no postamble.\n"
    )

    return f"{context_block}\n\n{articles_block}\n\n{highlights_block}\n{instructions}"


def estimate_cost(config, model, tokens_in, tokens_out):
    pricing = (config.get("pricing") or {}).get(model)
    if not pricing:
        return 0.0
    return (tokens_in / 1_000_000) * pricing["input"] + (tokens_out / 1_000_000) * pricing["output"]


def run_writer():
    config = load_config()
    sb = get_supabase()
    start = time.time()

    model = config.get("writer_model", "anthropic/claude-haiku-4-5")
    lang = config.get("writer_primary_language", "en")
    min_rel = int(config.get("writer_min_relevance", 6))
    max_themes = int(config.get("writer_max_themes", 5))
    min_themes = int(config.get("writer_min_themes", 3))
    max_per_theme = int(config.get("writer_max_articles_per_theme", 6))
    window_hours = int(config.get("writer_window_hours", 30))
    max_chars = int(config.get("writer_max_chars", 7000))

    print("OpenClaw Writer starting...")
    print(f"  Model:          {model}")
    print(f"  Language:       {lang}")
    print(f"  Window:         {window_hours}h")
    print(f"  Min relevance:  {min_rel}")
    print(f"  Themes:         {min_themes}-{max_themes}")
    print(f"  Max char count: {max_chars}")

    context = load_user_context(sb)
    print(f"  Interests:      {len(context['interests'])}")
    print(f"  Hypotheses:     {len(context['hypotheses'])}")

    articles, total_in_window = load_recent_analyzed_articles(sb, window_hours, min_rel)
    sources_map = load_sources_map(sb)

    print(f"  Articles in window:         {total_in_window}")
    print(f"  Articles meeting cutoff:    {len(articles)}\n")

    if len(articles) < min_themes:
        print(f"Only {len(articles)} articles meet cutoff. Need {min_themes}+. Lower writer_min_relevance and retry.")
        return

    clusters, leftovers = cluster_by_topic_overlap(articles, max_themes, max_per_theme)
    highlights_count = int(config.get("writer_highlights_count", 8))
    highlights_min_rel = int(config.get("writer_highlights_min_relevance", 8))
    highlights = pick_highlights(leftovers, highlights_count, highlights_min_rel)

    print(f"  Clusters formed: {len(clusters)}\n")
    for i, c in enumerate(clusters, 1):
        print(f"  Cluster {i}: {len(c)} articles, top: '{c[0]['title'][:70]}'")
    print(f"\n  Highlights selected: {len(highlights)}")
    for h in highlights:
        print(f"    rel={h['score'].get('relevance_score')} | {h['title'][:70]}")

    if len(clusters) < min_themes:
        print(f"\nOnly {len(clusters)} clusters. Need {min_themes}+. Briefing skipped.")
        return

    briefing_date = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d (%H:%M %Z)")
    system_prompt = load_prompt_files()
    relevant_count = len(articles)
    user_prompt = build_user_prompt(
        clusters, highlights, sources_map, context["by_id"], context,
        total_in_window, relevant_count, briefing_date, max_chars
    )

    print(f"\nGenerating briefing with {model}...")
    response = completion(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.3,
        max_tokens=4500,
    )
    briefing_text = response.choices[0].message.content.strip()

    usage = getattr(response, "usage", None)
    t_in = getattr(usage, "prompt_tokens", 0) if usage else 0
    t_out = getattr(usage, "completion_tokens", 0) if usage else 0
    cost = estimate_cost(config, model, t_in, t_out)
    duration_ms = int((time.time() - start) * 1000)

    print(f"\n{'-' * 60}")
    print(briefing_text)
    print(f"{'-' * 60}\n")
    print(f"Briefing chars: {len(briefing_text)} (limit: {max_chars})")
    print(f"Tokens: in={t_in} out={t_out} | Cost: ${cost:.4f} | Time: {duration_ms}ms")

    # Store
    content_col = f"content_{lang}"
    insert_row = {
        "date": datetime.now(timezone.utc).date().isoformat(),
        content_col: briefing_text,
        "model_writer": model,
        "cost_usd": round(cost, 6),
    }
    result = sb.table("briefings").insert(insert_row).execute()
    briefing_id = result.data[0]["id"] if result.data else None
    print(f"Saved briefing id={briefing_id}")

    sb.table("agent_runs").insert({
        "agent_name": "writer",
        "model_used": model,
        "tokens_in": t_in,
        "tokens_out": t_out,
        "cost_usd": round(cost, 6),
        "duration_ms": duration_ms,
        "status": "success",
    }).execute()


if __name__ == "__main__":
    run_writer()