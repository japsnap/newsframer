"""
NF-NEW10 — pre-analysis title dedup (collapse same-story wire pile-ups).

WHY: since the fetcher pulls up to 100/source and the global wires (Reuters/AP/CNN via
Google News) feed in, a single event arrives as 5-9 near-identical copies. The analyst
was paying to score every copy AND the brief over-represented wire-covered stories.

HOW (reuses work already done — no second clustering):
  * The deduplicator already groups same-story articles by embedding and stamps every
    member with `cluster_id` = the primary (earliest = originator), INCLUDING the
    "review-flagged" analysis clusters it conservatively KEEPS (sim 0.85-0.90).
  * This step takes those still-alive clusters, asks a CHEAP model (titles only) "is this
    one event?" as a safety confirm, and on YES soft-deletes all but the originator — so
    the analyst scores ONE copy per story. Soft-delete only: the audit trail is intact and
    the Writer can still see the full cluster via cluster_id.

SAFE BY DESIGN: reuses the proven embedding clusters; an LLM confirm guards against
collapsing two different-but-similar stories; DRY by default (prints, deletes nothing);
`--apply` performs the soft-deletes; config-gated; nothing else in the pipeline changes.

  python agents/title_dedup.py            # DRY: show what it WOULD collapse
  python agents/title_dedup.py --apply    # soft-delete the redundant copies
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
def select_drops(members):
    """Given a cluster's alive members (each {id, published_at, ...}), keep the EARLIEST
    published (the originator) and return (keeper, [drop members]). Deterministic; ties
    break by id so the choice is stable."""
    if len(members) < 2:
        return (members[0] if members else None), []
    ordered = sorted(members, key=lambda m: ((m.get("published_at") or ""), m.get("id") or ""))
    return ordered[0], ordered[1:]


def build_confirm_prompt(titles):
    """A titles-only yes/no: are these all the SAME news event? Conservative on purpose —
    one different headline => not the same event => keep all."""
    listed = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(titles))
    return (
        "An automated system flagged these news headlines as POSSIBLY the same story:\n\n"
        f"{listed}\n\n"
        "Do they ALL report the SAME specific news event (same who, what, and when)? "
        "If even one headline is about a DIFFERENT event — even on the same topic — answer false. "
        'Reply with ONLY a JSON object: {"same_event": true} or {"same_event": false}.'
    )


def parse_confirm(raw):
    """Tolerant parse -> True only on an explicit same_event:true. Anything unclear stays
    False so we KEEP all (never collapse on an ambiguous/garbled reply)."""
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
    """LLM confirm (injectable for tests). temperature/max_tokens come from config (no
    hard-coding). Defaults to False on any error -> keep all."""
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
    """Return {cluster_id: [member,...]} for alive, in-window articles whose cluster has
    2+ alive members. only_unscored (production default) restricts to articles the analyst
    has NOT scored yet, so we only ever collapse BEFORE the paid stage."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=window_hours)).isoformat()
    arts, start = [], 0
    while True:
        r = (sb.table("raw_articles")
             .select("id, title, published_at, cluster_id, source_id")
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


def run_title_dedup(apply=False, only_unscored=None):
    config = load_config()
    sb = get_supabase()
    model = config.get("title_dedup_model", config.get("classifier_model", "gemini/gemini-2.5-flash-lite"))
    window = int(config.get("title_dedup_window_hours", config.get("deduplicator_window_hours", 48)))
    if only_unscored is None:                       # None = use config; explicit arg (e.g. --all) overrides
        only_unscored = bool(config.get("title_dedup_only_unscored", True))
    temperature = config.get("title_dedup_temperature", 0)
    max_tokens = int(config.get("title_dedup_max_tokens", 20))
    t0 = time.time()

    print(f"NF-NEW10 Title-dedup [{'APPLY' if apply else 'DRY'}] | model={model} | window={window}h "
          f"| only_unscored={only_unscored}")
    clusters = load_alive_clusters(sb, window, only_unscored)
    print(f"  Alive multi-member clusters in window: {len(clusters)}")

    confirmed_drops = []   # member dicts to soft-delete
    kept_clusters = 0
    for cid, members in clusters.items():
        titles = [(m.get("title") or "") for m in members]
        same = confirm_same_event(titles, model, temperature, max_tokens)
        keeper, drops = select_drops(members)
        print("-" * 78)
        print(f"cluster {cid[:8]} | members={len(members)} | same_event={same} "
              f"-> {'COLLAPSE keep ' + keeper['id'][:8] if same else 'KEEP ALL'}")
        for m in members:
            tag = " <-- keep" if (same and m['id'] == keeper['id']) else (" drop" if same else "")
            print(f"    [{m['id'][:8]}] {(m.get('published_at') or '')[:19]} | {(m.get('title') or '')[:70]}{tag}")
        if same:
            confirmed_drops.extend(drops)
        else:
            kept_clusters += 1

    print("=" * 78)
    print(f"  Clusters: {len(clusters)} | collapsed: {len(clusters) - kept_clusters} | kept-all: {kept_clusters}")
    print(f"  Articles the analyst would SKIP (soft-deleted copies): {len(confirmed_drops)}")

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
        print(f"  APPLIED: soft-deleted {done}/{len(confirmed_drops)} redundant copies.")
    elif confirmed_drops:
        print("  DRY RUN — nothing deleted. Re-run with --apply to collapse.")

    duration_ms = int((time.time() - t0) * 1000)
    record_run(sb, {
        "agent_name": "title_dedup", "model_used": model,
        "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0,
        "duration_ms": duration_ms,
        "status": "success",
        "error": None if (apply or not confirmed_drops) else "dry-run",
    })
    return len(confirmed_drops)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="soft-delete the redundant copies (default: dry run)")
    ap.add_argument("--all", action="store_true",
                    help="DRY inspection: include already-scored articles too (see the full picture)")
    args = ap.parse_args()
    run_title_dedup(apply=args.apply, only_unscored=False if args.all else None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
