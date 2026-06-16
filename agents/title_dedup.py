"""
NF-NEW10 v2 — pre-analysis representative-set dedup (collapse same-story wire pile-ups
to a SMALL CURATED SET, not one article).

WHY: since the 100/source cap + global wires, a single event arrives as 5-9 copies. We
don't want to analyse all of them (cost + the event dominates the brief), but collapsing
to ONE risks (a) showing a prematurely-published partial instead of the developed story,
and (b) single-source / left-right bias. So per cluster we keep a representative SET,
chosen from METADATA ONLY (no article analysis), and the analyst scores just that set.

TWO AXES:
  * Temporal (EVERY topic): keep the EARLIEST (initial report) + the MOST-DEVELOPED
    (latest published, tie-broken by longest body) — so a partial early copy never hides
    the fuller later picture.
  * Bias balance (only categories in title_dedup_bias_categories, i.e. geopolitics +
    pakistan): also keep one source per Ground-News bias side PRESENT (left / center /
    right); a side with no source is skipped (never forced). DEPENDS on the source bias
    tags (NF-D1): until seeded, bias is unknown -> the axis degrades to no left/right split.

Reuses the deduplicator's clusters (cluster_id). A cheap titles-only LLM confirms the
cluster is really one event before anything is dropped (guards against merging two
different stories). Soft-delete only (audit trail intact; Writer still sees the cluster).
DRY by default; --apply collapses; --all inspects the whole window.

  python agents/title_dedup.py            # DRY: show the representative set per cluster
  python agents/title_dedup.py --apply    # soft-delete the non-representative copies
"""
import os
import sys
import time
import argparse
from collections import defaultdict
from datetime import datetime, timezone, timedelta

import yaml
from litellm import completion
from supabase import create_client

from dotenv import load_dotenv

from llm_json import parse_json_obj
from run_log import record_run

load_dotenv()
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_config():
    try:
        with open(os.path.join(BASE_DIR, "config", "models.yaml"), encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def get_supabase():
    return create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_KEY"))


# --- pure helpers (unit-tested) -------------------------------------------
def content_len(m):
    return len(m.get("content_raw") or "")


def normalize_bias(raw):
    """Ground-News bias string -> 'left' | 'center' | 'right' | None (None = unknown/unseeded)."""
    if not raw:
        return None
    s = str(raw).strip().lower()
    if "left" in s:
        return "left"
    if "right" in s:
        return "right"
    if "cent" in s or "middle" in s:
        return "center"
    return None


def select_representatives(members, bias_of=None, category_of=None, bias_categories=()):
    """Pick the representative set to KEEP from a same-story cluster (metadata only):
      - EARLIEST published (initial report) + MOST-DEVELOPED (latest; tie-break longest body).
      - If the cluster is bias-sensitive (a member's source category is in bias_categories),
        also one source per Ground-News bias side PRESENT (left/center/right), the most-
        developed within that side; a side with no source is skipped.
    Returns (sorted keep_ids, [drop members]). <2 members -> keep all."""
    bias_of = bias_of or {}
    category_of = category_of or {}
    if len(members) < 2:
        return [m["id"] for m in members], []
    earliest = min(members, key=lambda m: ((m.get("published_at") or ""), m.get("id") or ""))
    developed = max(members, key=lambda m: ((m.get("published_at") or ""), content_len(m), m.get("id") or ""))
    keep = {earliest["id"], developed["id"]}

    cats = {category_of.get(m.get("source_id")) for m in members}
    if bias_categories and (cats & set(bias_categories)):
        best_per_side = {}
        for m in members:
            side = normalize_bias(bias_of.get(m.get("source_id")))
            if not side:
                continue
            cur = best_per_side.get(side)
            if cur is None or ((m.get("published_at") or ""), content_len(m)) > \
                              ((cur.get("published_at") or ""), content_len(cur)):
                best_per_side[side] = m
        for m in best_per_side.values():
            keep.add(m["id"])

    drops = [m for m in members if m["id"] not in keep]
    return sorted(keep), drops


def build_confirm_prompt(titles):
    """A titles-only yes/no: are these all the SAME news event? Conservative on purpose."""
    listed = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(titles))
    return (
        "An automated system flagged these news headlines as POSSIBLY the same story:\n\n"
        f"{listed}\n\n"
        "Do they ALL report the SAME specific news event (same who, what, and when)? "
        "If even one headline is about a DIFFERENT event — even on the same topic — answer false. "
        'Reply with ONLY a JSON object: {"same_event": true} or {"same_event": false}.'
    )


def parse_confirm(raw):
    """Tolerant parse -> True only on an explicit same_event:true (ambiguous stays False)."""
    try:
        obj = parse_json_obj(raw)
    except Exception:
        return False
    if not isinstance(obj, dict):
        return False
    v = obj.get("same_event")
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("true", "yes", "1")
    return False


def confirm_same_event(titles, model, temperature, max_tokens, _completion=completion):
    """LLM confirm (injectable for tests). temperature/max_tokens from config; False on error."""
    try:
        resp = _completion(
            model=model,
            messages=[{"role": "user", "content": build_confirm_prompt(titles)}],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return parse_confirm(resp.choices[0].message.content)
    except Exception as e:
        print(f"    confirm error ({type(e).__name__}); keeping all: {e}")
        return False


# --- data ------------------------------------------------------------------
def load_alive_clusters(sb, window_hours, only_unscored=True):
    """{cluster_id: [member,...]} for alive, in-window articles whose cluster has 2+ alive
    members. only_unscored restricts to articles the analyst hasn't scored (pre-paid stage)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=window_hours)).isoformat()
    arts, start = [], 0
    while True:
        r = (sb.table("raw_articles")
             .select("id, title, published_at, cluster_id, source_id, content_raw")
             .is_("deleted_at", "null").not_.is_("cluster_id", "null")
             .gte("published_at", cutoff)
             .order("published_at", desc=False)
             .range(start, start + 999).execute())
        batch = r.data or []
        arts.extend(batch)
        if len(batch) < 1000:
            break
        start += 1000

    if only_unscored and arts:
        ids = [a["id"] for a in arts]
        scored = set()
        for i in range(0, len(ids), 50):
            d = (sb.table("analyst_scores").select("article_id")
                 .in_("article_id", ids[i:i + 50]).execute())
            for row in (d.data or []):
                scored.add(row["article_id"])
        arts = [a for a in arts if a["id"] not in scored]

    groups = defaultdict(list)
    for a in arts:
        groups[a["cluster_id"]].append(a)
    return {cid: ms for cid, ms in groups.items() if len(ms) >= 2}


def load_source_meta(sb):
    """(bias_of, category_of) keyed by source_id. The Ground-News bias column may be absent
    or unseeded (NF-D1) -> bias_of stays empty and the bias axis degrades to no split."""
    category_of, bias_of = {}, {}
    try:
        rows = (sb.table("sources").select("id, category, groundnews_publication_bias")
                .limit(2000).execute()).data or []
        for s in rows:
            category_of[s["id"]] = s.get("category")
            bias_of[s["id"]] = s.get("groundnews_publication_bias")
    except Exception:
        rows = (sb.table("sources").select("id, category").limit(2000).execute()).data or []
        for s in rows:
            category_of[s["id"]] = s.get("category")
    return bias_of, category_of


def run_title_dedup(apply=False, only_unscored=None):
    config = load_config()
    sb = get_supabase()
    model = config.get("title_dedup_model", config.get("classifier_model", "gemini/gemini-2.5-flash-lite"))
    window = int(config.get("title_dedup_window_hours", config.get("deduplicator_window_hours", 48)))
    if only_unscored is None:
        only_unscored = bool(config.get("title_dedup_only_unscored", True))
    temperature = config.get("title_dedup_temperature", 0)
    max_tokens = int(config.get("title_dedup_max_tokens", 20))
    bias_categories = config.get("title_dedup_bias_categories", ["geopolitics", "pakistan"])
    t0 = time.time()

    print(f"NF-NEW10 Title-dedup v2 [{'APPLY' if apply else 'DRY'}] | model={model} | window={window}h "
          f"| only_unscored={only_unscored} | bias_categories={bias_categories}")
    clusters = load_alive_clusters(sb, window, only_unscored)
    bias_of, category_of = load_source_meta(sb)
    bias_seeded = any(normalize_bias(v) for v in bias_of.values())
    print(f"  Alive multi-member clusters: {len(clusters)} | Ground-News bias tags seeded: {bias_seeded}")

    confirmed_drops = []
    kept_all = 0
    for cid, members in clusters.items():
        same = confirm_same_event([m.get("title") or "" for m in members], model, temperature, max_tokens)
        keep_ids, drops = select_representatives(members, bias_of, category_of, bias_categories)
        keep_set = set(keep_ids)
        print("-" * 78)
        print(f"cluster {cid[:8]} | members={len(members)} | same_event={same} -> "
              f"{'KEEP ' + str(len(keep_ids)) + ' (drop ' + str(len(drops)) + ')' if same else 'KEEP ALL (unconfirmed)'}")
        for m in members:
            role = (" <-- keep" if m["id"] in keep_set else " drop") if same else ""
            print(f"    [{m['id'][:8]}] {(m.get('published_at') or '')[:19]} "
                  f"cat={category_of.get(m.get('source_id'))} bias={normalize_bias(bias_of.get(m.get('source_id')))} "
                  f"len={content_len(m):4} | {(m.get('title') or '')[:50]}{role}")
        if same:
            confirmed_drops.extend(drops)
        else:
            kept_all += 1

    print("=" * 78)
    print(f"  Clusters: {len(clusters)} | collapsed: {len(clusters) - kept_all} | kept-all (unconfirmed): {kept_all}")
    print(f"  Non-representative copies the analyst would SKIP: {len(confirmed_drops)}")

    if apply and confirmed_drops:
        now = datetime.now(timezone.utc).isoformat()
        done = 0
        for m in confirmed_drops:
            try:
                sb.table("raw_articles").update(
                    {"deleted_at": now, "duplicate_of": m["cluster_id"]}
                ).eq("id", m["id"]).execute()
                done += 1
            except Exception as e:
                print(f"    soft-delete failed for {m['id'][:8]}: {e}")
        print(f"  APPLIED: soft-deleted {done}/{len(confirmed_drops)} non-representative copies.")
    elif confirmed_drops:
        print("  DRY RUN — nothing deleted. Re-run with --apply to collapse.")

    record_run(sb, {
        "agent_name": "title_dedup", "model_used": model,
        "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0,
        "duration_ms": int((time.time() - t0) * 1000),
        "status": "success",
        "error": None if (apply or not confirmed_drops) else "dry-run",
    })
    return len(confirmed_drops)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="soft-delete the non-representative copies (default: dry)")
    ap.add_argument("--all", action="store_true", help="DRY inspection: include already-scored articles too")
    args = ap.parse_args()
    run_title_dedup(apply=args.apply, only_unscored=False if args.all else None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
