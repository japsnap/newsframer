"""
NF-C1 — News-context-shift sequencing (spec §4.4). A Writer post-pass, NOT a new engine.

When a developing story stays live across days and its TRACKED FACT changes, emit one concise,
sourced "what changed" note — the delta, DATA-TO-DATA (§4.3): today's structured fact vs the
STORED prior fact, number<->number / status<->status, each side backed by article IDs. NEVER a
diff of prose or of a previously-written brief. If nothing material changed, emit nothing.

The 7 delta types (§4.4): magnitude, cumulative tally, status/lifecycle, reversal/contradiction,
scope/spread, attribution resolved, forecast-vs-actual.

Mechanism:
  Stage 0 (≈free, no LLM): match today's brief stories to existing threads by embedding cosine
    (reuse the deduplicator's stored vectors + cosine_similarity). cluster_id is the 48h spine;
    the embedding bridges the full 7-day context window.
  Stage A (cheap model): extract today's STRUCTURED fact for a matched/developing story.
  Diff: classify_delta() compares it to the stored prior point; only past the materiality bar
    does it become a note. Trajectory keeps the last-N points (cumulative tally needs the path).

Persistence: the Supabase `tracked_threads` table. Weekly hard reset (§4.2): threads from before
the current Monday-06:00-JST boundary are deactivated, breaking the hallucination chain.

OFF BY DEFAULT (`sequencing_enabled: false`) -> the Writer never calls this and the brief is
byte-for-byte unchanged. Fully wrapped where wired: any failure is isolated and can never break
or alter the live brief.

    venv\\Scripts\\python.exe agents/thread_tracker.py --simulate   (read-only 7-day replay)
    venv\\Scripts\\python.exe tests/test_thread_tracker.py
"""
import os
import re
import sys
import json
import argparse
from datetime import datetime, timezone, timedelta

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from deduplicator import parse_embedding, cosine_similarity  # noqa: E402  (pure; reuse vectors)
from llm_json import parse_json_obj  # noqa: E402  (tolerant LLM-JSON parse)


def _load_config():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(base_dir, "config", "models.yaml"), "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# Module-level config read, wrapped so a missing/broken config can't break import
# (falls back to the literal default below, reproducing prior behaviour). Reads the
# yaml directly to avoid a circular import with writer (which imports this module).
try:
    _CFG = _load_config() or {}
except Exception:
    _CFG = {}

JST = timezone(timedelta(hours=int(_CFG.get("operator_tz_offset_hours", 9))))  # operator timezone (JST = +9), config-driven
WHAT_CHANGED_HEADING = str(_CFG.get("what_changed_section_header", "## 📈 What Changed"))
NUMERIC_TYPES = ("magnitude", "cumulative", "forecast")
CATEGORICAL_TYPES = ("status", "reversal", "scope", "attribution")
ALL_DELTA_TYPES = NUMERIC_TYPES + CATEGORICAL_TYPES


# =====================================================================================
# PURE CORE (no DB, no LLM) — the part pinned by tests/test_thread_tracker.py
# =====================================================================================

def week_start_jst(now_utc):
    """The most recent Monday-06:00-JST boundary at/before `now_utc`, as a JST datetime.
    Threads whose week_start predates this boundary belong to a prior chain and are reset (§4.2)."""
    now_j = now_utc.astimezone(JST)
    monday = (now_j - timedelta(days=now_j.weekday())).replace(hour=6, minute=0, second=0, microsecond=0)
    if now_j < monday:                      # before Mon 06:00 -> still last week's chain
        monday = monday - timedelta(days=7)
    return monday


def week_start_key(now_utc):
    """ISO date string of the current chain's Monday (the tracked_threads.week_start value)."""
    return week_start_jst(now_utc).date().isoformat()


_NUM_RE = re.compile(r"(-?\d[\d,]*\.?\d*)")
_SUFFIX = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mn": 1e6, "million": 1e6,
           "b": 1e9, "bn": 1e9, "billion": 1e9, "trillion": 1e12}


def parse_quantity(value):
    """Extract a leading numeric magnitude from a value -> (number, unit) or None.
    Handles '47', '47 dead', '$5M', '5 million', '20,000 acres', '40%', 12 (int/float).
    Pure; returns None when no number is present (caller falls back to a string compare)."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return (float(value), None)
    s = str(value).strip().lower()
    if not s:
        return None
    m = _NUM_RE.search(s)
    if not m:
        return None
    num = float(m.group(1).replace(",", ""))
    rest = s[m.end():].strip()
    # scale suffix immediately after the number (e.g. "5m", "5 million")
    word = re.match(r"([a-z]+)", rest)
    if word and word.group(1) in _SUFFIX:
        num *= _SUFFIX[word.group(1)]
        rest = rest[word.end():].strip()
    if "%" in s:
        return (num, "%")
    unit = rest.split()[0] if rest else None
    return (num, unit)


def _norm(s):
    return re.sub(r"\s+", " ", str(s or "").strip().lower())


def is_material_numeric(old_num, new_num, pct_thresh, abs_thresh):
    """True if |new-old| clears EITHER the absolute OR the relative (pct of |old|) bar. Pure.
    An abs_thresh <= 0 DISABLES the absolute bar (percentage-only) — used by the crypto/price
    override (NF-C1a) so a large number like a price counts only on a >=pct move, never on a tiny
    absolute wiggle. A pct_thresh of 0 keeps the legacy 'any non-negative ratio' behaviour
    (cumulative tallies clear on any real climb). All existing configs use abs_thresh=1, so their
    behaviour is unchanged."""
    change = abs(new_num - old_num)
    if abs_thresh > 0 and change >= abs_thresh:
        return True
    base = abs(old_num)
    return base > 0 and (change / base) >= pct_thresh


def _type_thresholds(materiality, dtype):
    """(pct, abs) bar for a numeric type, from config with safe defaults."""
    defaults = {"magnitude": (0.15, 1.0), "cumulative": (0.0, 1.0), "forecast": (0.10, 1.0)}
    d_pct, d_abs = defaults.get(dtype, (0.15, 1.0))
    m = materiality or {}
    return (float(m.get(f"{dtype}_pct", d_pct)), float(m.get(f"{dtype}_abs", d_abs)))


def resolve_materiality(config, category):
    """Global sequencing_materiality with the per-category override merged on top (config-driven,
    NF-C1a; a future settings-UI writes the overrides). A category with no override -> the global
    bars unchanged. Only the keys present in the override are replaced. Pure over its inputs."""
    base = dict(config.get("sequencing_materiality", {}) or {})
    overrides = config.get("sequencing_materiality_overrides", {}) or {}
    ov = overrides.get(category) if category else None
    if isinstance(ov, dict):
        base.update(ov)
    return base


def _family(dtype):
    """The comparison family of a delta type: 'num' (compare numbers), 'cat' (compare labels),
    or None (unknown). A delta is only ever computed WITHIN one family."""
    if dtype in NUMERIC_TYPES:
        return "num"
    if dtype in CATEGORICAL_TYPES:
        return "cat"
    return None


def _delta(dtype, prior_point, new_fact, **extra):
    """Build a delta dict, always carrying BOTH sides' article IDs (data-to-data, §4.3)."""
    return {"type": dtype, "since": prior_point.get("as_of"),
            "old": prior_point.get("value"), "new": new_fact.get("value"),
            "old_ids": prior_point.get("article_ids", []),
            "new_ids": new_fact.get("article_ids", []), **extra}


def classify_delta(prior_point, new_fact, materiality=None):
    """Compare today's extracted fact to the stored prior point -> a delta dict or None.

    prior_point: {value, unit, as_of, delta_type, article_ids} (the stored last point) or None.
    new_fact:    {value, unit, delta_type, article_ids} extracted today.
    Pure / data-to-data — only the two structured values are compared, never prose. Returns None on:
    no prior (first sighting), a cross-FAMILY flip (a status story that today reads numeric is
    ambiguous -> skip, never invent a 'reached -> 24' note), unparseable numbers, or a sub-bar
    change. Every returned delta carries old_ids AND new_ids."""
    if not prior_point or not new_fact:
        return None
    new_val = new_fact.get("value")
    if new_val is None or new_val == "":
        return None
    pf, nf = _family(prior_point.get("delta_type")), _family(new_fact.get("delta_type"))
    if pf is None or nf is None or pf != nf:
        return None                                       # cross-family / unknown -> ambiguous, skip

    if nf == "num":
        o, n = parse_quantity(prior_point.get("value")), parse_quantity(new_val)
        if o is None or n is None:
            return None                                   # not actually numeric -> skip (no string guess)
        on, nn = o[0], n[0]
        dtype = new_fact.get("delta_type")
        if dtype == "cumulative" and nn <= on:
            return None                                   # a running tally must climb
        pct, absth = _type_thresholds(materiality, dtype)
        if not is_material_numeric(on, nn, pct, absth):
            return None
        return _delta(dtype, prior_point, new_fact, unit=new_fact.get("unit") or prior_point.get("unit"))

    # categorical: material iff the label actually changed
    if _norm(prior_point.get("value")) == _norm(new_val):
        return None
    return _delta(new_fact.get("delta_type"), prior_point, new_fact, unit=None)


def _since_label(since_iso):
    try:
        dt = datetime.fromisoformat(str(since_iso).replace("Z", "+00:00"))
        return dt.astimezone(JST).strftime("%b %-d") if os.name != "nt" else dt.astimezone(JST).strftime("%b %#d")
    except (ValueError, TypeError):
        return "earlier"


_DEFAULT_PRICE_UNITS = ("$", "usd", "dollar", "dollars", "eur", "gbp", "jpy", "yen")


def _is_currency(unit, price_units=None):
    """True if `unit` marks a price (config sequencing_price_units, case-insensitive). Pure."""
    if not unit:
        return False
    pool = [str(x).strip().lower() for x in (price_units or _DEFAULT_PRICE_UNITS)]
    return str(unit).strip().lower() in pool


def _humanize(num):
    """66000 -> '66K', 1_500_000 -> '1.5M', 47 -> '47'. Sign-preserving, K/M/B/T. Pure."""
    try:
        n = float(num)
    except (TypeError, ValueError):
        return str(num)
    sign = "-" if n < 0 else ""
    a = abs(n)
    for div, suf in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if a >= div:
            s = f"{a / div:.1f}".rstrip("0").rstrip(".")
            return f"{sign}{s}{suf}"
    return f"{sign}{int(a)}" if a == int(a) else f"{sign}{a:g}"


def format_shift_note(label, delta, source_link=None, price_units=None):
    """One-line, data-to-data shift note. source_link (optional) = '[Source](url)' for the NEW fact.
    Pure; the figures come only from the structured delta, never from prose. A PRICE fact (numeric
    type with a currency unit, NF-C1a) renders readably as 'was $X on DAY, now $Y (+p%)' with
    humanized K/M figures and the percentage move; every other shape keeps the compact arrow form."""
    since = _since_label(delta.get("since"))
    t = delta.get("type")
    raw_unit = delta.get("unit")

    if t in ("magnitude", "cumulative", "forecast") and _is_currency(raw_unit, price_units):
        o, n = parse_quantity(delta.get("old")), parse_quantity(delta.get("new"))
        if o is not None and n is not None:
            move = ""
            if o[0]:
                p = round((n[0] - o[0]) / abs(o[0]) * 100)
                move = f" ({'+' if p >= 0 else '−'}{abs(p)}%)"
            body = f"{label}: was ${_humanize(o[0])} on {since}, now ${_humanize(n[0])}{move}"
            return f"{body} {source_link}".rstrip() if source_link else body

    unit = (" " + raw_unit) if raw_unit and raw_unit != "%" else ""
    pct = "%" if raw_unit == "%" else ""
    if t in ("magnitude", "cumulative", "forecast"):
        body = f"{label}: {delta['old']}{pct} → {delta['new']}{pct}{unit} (since {since})"
    elif t == "reversal":
        body = f"{label}: reversed — was {delta['old']}, now {delta['new']} (since {since})"
    else:  # status / scope / attribution
        body = f"{label}: {delta['old']} → {delta['new']} (since {since})"
    return f"{body} {source_link}".rstrip() if source_link else body


def cap_points(points, max_points):
    """Keep the most-recent `max_points` trajectory points (cumulative tally needs the path)."""
    n = max(1, int(max_points))
    return list(points or [])[-n:]


def render_what_changed_section(notes):
    """Build the '## 📈 What Changed' subsection from rendered note lines. '' when none."""
    lines = [n for n in (notes or []) if n]
    if not lines:
        return ""
    return WHAT_CHANGED_HEADING + "\n" + "\n".join(f"- {ln}" for ln in lines)


def splice_what_changed(briefing_text, section):
    """Insert the What-Changed section just before the footer rule (---), else append.
    No section -> text unchanged. Mirrors the Investigations splice."""
    if not section:
        return briefing_text
    marker = "\n---\n"
    idx = briefing_text.rfind(marker)
    if idx == -1:
        return briefing_text.rstrip() + "\n\n" + section + "\n"
    return briefing_text[:idx] + "\n\n" + section + "\n" + briefing_text[idx:]


# =====================================================================================
# Stage A — structured fact extraction (cheap model)
# =====================================================================================

EXTRACT_SYSTEM = str(_CFG.get("sequencing_extract_system_prompt", (
    "You extract ONE structured, factual data point from news article text about a single ongoing "
    "story, for day-over-day change tracking. Return ONLY a JSON object:\n"
    '{"delta_type": "...", "value": "...", "unit": "...", "short_fact": "...", "confidence": 0.0}\n'
    "- delta_type: one of magnitude, cumulative, status, reversal, scope, attribution, forecast — "
    "the KIND of fact most central to this story's progression.\n"
    "- value: the current value. A NUMBER (as a string is fine) for magnitude/cumulative/forecast "
    "(e.g. '47', '$5M', '20000'); a SHORT label for status/reversal/scope/attribution "
    "(e.g. 'passed committee', 'arson', 'Gaza+Lebanon').\n"
    "- unit: e.g. 'dead', 'acres', 'USD', '%', or '' if none.\n"
    "- short_fact: <=80 chars, the bare fact (e.g. 'death toll 47').\n"
    "- confidence: 0..1 that this value is stated (not inferred) in the text.\n"
    "Use ONLY facts present in the text. If no trackable hard fact, return value ''. No prose."
)))


def build_extract_prompt(label, article_texts, max_chars=1200):
    body = "\n\n".join(f"[{i+1}] {(t or '')[:max_chars]}" for i, t in enumerate(article_texts))
    return f"Story: {label}\n\nArticle text (today):\n{body}\n\nExtract the structured fact JSON."


def extract_fact(label, article_texts, article_ids, model, temperature, max_tokens,
                 _completion=None, snippet_chars=1200, timeout=None):
    """Stage A: cheap-model structured extraction. Returns a fact dict (article_ids attached from
    the REAL today-cluster ids, never trusted from the model) or None. Tolerant of bad JSON.
    `timeout` (2026-06-22) hard-bounds the LLM call so a hung Gemini can't hang the writer; the
    caller's breaker aborts sequencing after a few timeouts. timeout=None = unbounded (tests)."""
    if _completion is None:
        from litellm import completion as _completion
    prompt = build_extract_prompt(label, article_texts, snippet_chars)

    def _do():
        return _completion(model=model,
                           messages=[{"role": "system", "content": EXTRACT_SYSTEM},
                                     {"role": "user", "content": prompt}],
                           temperature=temperature, max_tokens=max_tokens)

    if timeout:
        from llm_client import call_bounded
        resp = call_bounded(_do, timeout)
    else:
        resp = _do()
    raw = resp.choices[0].message.content
    try:
        obj = parse_json_obj(raw)
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    dtype = obj.get("delta_type")
    val = obj.get("value")
    if dtype not in ALL_DELTA_TYPES or val in (None, ""):
        return None
    return {"delta_type": dtype, "value": val, "unit": obj.get("unit") or None,
            "short_fact": (obj.get("short_fact") or "")[:120],
            "confidence": obj.get("confidence"), "article_ids": list(article_ids)}


# =====================================================================================
# DB + orchestration (wrapped; never raises into the brief)
# =====================================================================================

def _get_supabase():
    from writer import get_supabase
    return get_supabase()


def _load_categories(sb):
    """source_id -> category map (reuse the writer's loader). Best-effort: {} on any failure so
    sequencing degrades to the GLOBAL materiality bars and never breaks the brief (NF-C1a)."""
    try:
        from writer import load_source_categories
        return load_source_categories(sb) or {}
    except Exception:
        return {}


def load_active_threads(sb, week_key):
    """Active threads for the CURRENT week chain (others were reset, §4.2)."""
    r = (sb.table("tracked_threads").select("*")
         .eq("active", True).eq("week_start", week_key).execute())
    return r.data or []


def reset_stale_threads(sb, week_key):
    """§4.2 Monday reset: deactivate any active thread from an earlier chain. Returns count."""
    r = (sb.table("tracked_threads").select("id")
         .eq("active", True).neq("week_start", week_key).execute())
    stale = [row["id"] for row in (r.data or [])]
    for tid in stale:
        sb.table("tracked_threads").update({"active": False}).eq("id", tid).execute()
    return len(stale)


def _majority_category(cats):
    """Most common non-null category in a story's articles, or None. Pure."""
    counts = {}
    for c in cats:
        if c:
            counts[c] = counts.get(c, 0) + 1
    return max(counts, key=counts.get) if counts else None


def brief_stories(clusters, categories_map=None):
    """Group today's brief articles into developing-story units by dedup cluster_id. A cluster_id
    group (multi-outlet, recurring) is a story; singletons without a cluster_id are skipped for
    SEEDING but can still MATCH an existing thread by embedding. Returns list of story dicts:
    {key, label, article_ids, texts, has_cluster, category}. `category` (the source bundle, §8.1)
    is the most common category among the story's articles — it selects the per-category
    materiality override (NF-C1a); None when no map is given or no category resolves."""
    cmap = categories_map or {}
    by_cluster = {}
    singles = []
    for theme_idx, cluster in enumerate(clusters or []):
        for a in cluster:
            cid = a.get("cluster_id")
            entry = {"id": a.get("id"), "title": a.get("title") or "",
                     "text": a.get("content_raw") or "", "theme_idx": theme_idx,
                     "category": cmap.get(a.get("source_id"))}
            if cid:
                by_cluster.setdefault(cid, {"theme_idx": theme_idx, "members": []})["members"].append(entry)
            else:
                singles.append((theme_idx, entry))
    stories = []
    for cid, grp in by_cluster.items():
        members = grp["members"]
        stories.append({
            "key": str(cid), "label": (members[0]["title"] or "story")[:80],
            "article_ids": [m["id"] for m in members], "texts": [m["text"] for m in members],
            "theme_idx": grp["theme_idx"], "has_cluster": True,
            "category": _majority_category([m["category"] for m in members]),
        })
    for theme_idx, e in singles:
        stories.append({
            "key": str(e["id"]), "label": (e["title"] or "story")[:80],
            "article_ids": [e["id"]], "texts": [e["text"]], "theme_idx": theme_idx,
            "has_cluster": False, "category": e["category"],
        })
    return stories


def fetch_embeddings(sb, article_ids):
    """{article_id: [floats]} for the given ids (reuse the deduplicator's stored vectors)."""
    out = {}
    ids = list(article_ids)
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        r = sb.table("raw_articles").select("id, embedding").in_("id", chunk).execute()
        for row in (r.data or []):
            vec = parse_embedding(row.get("embedding"))
            if vec is not None:
                out[row["id"]] = vec
    return out


def match_thread(story_vec, threads, threshold):
    """Stage 0: best cosine match of a story's vector to an existing thread's embedding.
    Returns (thread, score) or (None, 0.0). Pure over the loaded threads."""
    best, best_s = None, 0.0
    if story_vec is None:
        return (None, 0.0)
    for t in threads:
        tv = parse_embedding(t.get("embedding"))
        if tv is None:
            continue
        s = cosine_similarity(story_vec, tv)
        if s > best_s:
            best, best_s = t, s
    return (best, best_s) if best_s >= threshold else (None, best_s)


def detect_and_record(sb, config, clusters, sources_map, now_utc, apply=True, log=print):
    """The post-pass. Returns (notes, section):
      notes   = [{theme_idx, line, old_ids, new_ids}] for inline weaving,
      section = the rendered '## 📈 What Changed' subsection (or '').
    Wrapped by the caller; on `apply` it persists thread state. Never raises into the brief."""
    model = config.get("sequencing_model", config.get("title_dedup_model", "gemini/gemini-2.5-flash-lite"))
    temperature = float(config.get("sequencing_temperature", 0))
    max_tokens = int(config.get("sequencing_max_tokens", 200))
    sim = float(config.get("sequencing_match_similarity", 0.83))
    max_threads = int(config.get("sequencing_max_threads_per_run", 40))
    max_notes = int(config.get("sequencing_max_notes_per_brief", 5))
    traj = int(config.get("sequencing_trajectory_points", 3))
    min_conf = float(config.get("sequencing_min_confidence", 0.5))
    price_units = config.get("sequencing_price_units", None)
    week_key = week_start_key(now_utc)
    # 2026-06-22: bound each extraction; abort sequencing after a few consecutive failures so a
    # dead Gemini can't hang the writer (sequencing is optional — the brief builds without notes).
    timeout_s = float(config.get("llm_request_timeout_seconds", 60))
    brk = int(config.get("llm_breaker_threshold", 3))
    consec_fail = 0

    reset_n = reset_stale_threads(sb, week_key) if apply else 0
    threads = load_active_threads(sb, week_key)
    categories_map = _load_categories(sb)
    stories = brief_stories(clusters, categories_map)
    all_ids = [i for s in stories for i in s["article_ids"]]
    embs = fetch_embeddings(sb, all_ids)
    log(f"  NF-C1: week {week_key} | reset {reset_n} stale | {len(threads)} active thread(s) | "
        f"{len(stories)} brief stor(y/ies)")

    notes, checked = [], 0
    for story in stories:
        if checked >= max_threads or len(notes) >= max_notes:
            break
        vec = _story_vector(story, embs)
        matched, score = match_thread(vec, threads, sim)
        if matched is None and not story["has_cluster"]:
            continue                                    # don't seed single-source noise
        checked += 1
        try:
            fact = extract_fact(story["label"], story["texts"], story["article_ids"],
                                model, temperature, max_tokens,
                                snippet_chars=int(config.get("sequencing_snippet_chars", 1200)),
                                timeout=timeout_s)
            consec_fail = 0
        except Exception as e:
            consec_fail += 1
            log(f"  NF-C1: extract failed for {story['label'][:40]!r}: {type(e).__name__}: {e}")
            if consec_fail >= brk:
                log(f"  NF-C1: extraction LLM unreachable ({consec_fail}x) — aborting sequencing; "
                    f"brief built without 'What Changed' notes.")
                break
            continue
        if not fact:
            continue
        conf = fact.get("confidence")
        if conf is not None and float(conf) < min_conf:
            continue                                    # low-confidence extraction -> don't store or emit
        fact["as_of"] = now_utc.isoformat()
        prior = (matched.get("points") or [None])[-1] if matched else None
        mat = resolve_materiality(config, story.get("category"))
        delta = classify_delta(prior, fact, mat)
        if delta:
            link = _source_link(story, sources_map, sb)
            line = format_shift_note(_clean_label((matched or {}).get("label") or story["label"]),
                                     delta, link, price_units)
            notes.append({"theme_idx": story["theme_idx"], "line": line,
                          "old_ids": delta.get("old_ids", []), "new_ids": delta.get("new_ids", [])})
            log(f"  NF-C1 DELTA [{delta['type']}] {line}")
        if apply:
            _upsert_thread(sb, matched, story, fact, vec, week_key, now_utc, traj)

    section = render_what_changed_section([n["line"] for n in notes])
    return notes, section


def _story_vector(story, embs):
    vecs = [embs[i] for i in story["article_ids"] if i in embs]
    if not vecs:
        return None
    if len(vecs) == 1:
        return vecs[0]
    dim = len(vecs[0])
    return [sum(v[k] for v in vecs) / len(vecs) for k in range(dim)]   # centroid


def _clean_label(label):
    """Short, stable thread label: collapse whitespace, cut at a WORD boundary ~48 chars, trim
    trailing punctuation so it never ends mid-word or on a stray ':'/'—'."""
    s = re.sub(r"\s+", " ", (label or "").strip())
    if not s:
        return "story"
    if len(s) > 48:
        s = s[:48].rsplit(" ", 1)[0]
    return s.rstrip(" ,;:-—") or "story"


def _source_link(story, sources_map, sb):
    """[Source](url) for the story's newest article, mirroring NF-NEW1 citations. Best-effort."""
    try:
        aid = story["article_ids"][0]
        r = sb.table("raw_articles").select("url, source_id").eq("id", aid).limit(1).execute()
        row = (r.data or [{}])[0]
        name = sources_map.get(row.get("source_id"), "source")
        url = row.get("url")
        return f"[{name}]({url})" if url else ""
    except Exception:
        return ""


def _upsert_thread(sb, matched, story, fact, vec, week_key, now_utc, traj):
    point = {"as_of": fact["as_of"], "value": fact["value"], "unit": fact.get("unit"),
             "short_fact": fact.get("short_fact"), "article_ids": fact["article_ids"],
             "delta_type": fact["delta_type"]}
    if matched:
        points = cap_points((matched.get("points") or []) + [point], traj)
        upd = {"points": points, "last_seen_at": now_utc.isoformat(),
               "delta_type": fact["delta_type"], "cluster_id": _maybe_uuid(story["key"])}
        if vec is not None:
            upd["embedding"] = vec
        sb.table("tracked_threads").update(upd).eq("id", matched["id"]).execute()
    else:
        row = {"label": _clean_label(story["label"]), "delta_type": fact["delta_type"],
               "points": [point], "week_start": week_key, "active": True,
               "cluster_id": _maybe_uuid(story["key"]),
               "last_seen_at": now_utc.isoformat()}
        if vec is not None:
            row["embedding"] = vec
        sb.table("tracked_threads").insert(row).execute()


def _maybe_uuid(key):
    return key if re.match(r"^[0-9a-fA-F-]{36}$", str(key) or "") else None


# =====================================================================================
# Standalone read-only verification (no live send, builds NO live thread rows)
# =====================================================================================

def _simulate(days=7):
    """Replay the last `days` of briefs in time order against an IN-MEMORY store and print the
    data-to-data deltas + backing article IDs. Proves the mechanism on real data with ZERO writes
    to the live brief or the live tracked_threads table. Stage A LLM calls only (cheap)."""
    from writer import load_config, get_supabase
    config = load_config()
    sb = get_supabase()
    model = config.get("sequencing_model", "gemini/gemini-2.5-flash-lite")
    traj = int(config.get("sequencing_trajectory_points", 3))
    sim = float(config.get("sequencing_match_similarity", 0.83))
    min_conf = float(config.get("sequencing_min_confidence", 0.5))
    price_units = config.get("sequencing_price_units", None)
    categories_map = _load_categories(sb)

    r = (sb.table("briefings").select("id, date, created_at, article_ids")
         .order("created_at", desc=True).limit(days).execute())
    briefs = list(reversed(r.data or []))
    print(f"Replaying {len(briefs)} brief(s) in time order (in-memory; no writes)...\n")
    mem = []                                  # in-memory threads: {label, embedding, points}
    type_examples = {}
    for b in briefs:
        ids = b.get("article_ids") or []
        if isinstance(ids, str):
            ids = json.loads(ids)
        arts = _load_articles(sb, ids)
        clusters = _fake_clusters(arts)
        now = _parse_ts(b.get("created_at"))
        embs = fetch_embeddings(sb, [a["id"] for a in arts])
        stories = brief_stories(clusters, categories_map)
        day_deltas = 0
        for story in stories:
            if not story["has_cluster"]:
                continue
            vec = _story_vector(story, embs)
            matched, _s = match_thread(vec, mem, sim)
            try:
                fact = extract_fact(story["label"], story["texts"], story["article_ids"],
                                    model, float(config.get("sequencing_temperature", 0)),
                                    int(config.get("sequencing_max_tokens", 200)))
            except Exception as e:
                print(f"   extract error: {type(e).__name__}: {e}")
                continue
            if not fact:
                continue
            conf = fact.get("confidence")
            if conf is not None and float(conf) < min_conf:
                continue
            fact["as_of"] = now.isoformat()
            prior = (matched.get("points") if matched else None) or [None]
            mat = resolve_materiality(config, story.get("category"))
            delta = classify_delta(prior[-1], fact, mat)
            if delta:
                day_deltas += 1
                lbl = _clean_label((matched or {}).get("label") or story["label"])
                note = format_shift_note(lbl, delta, price_units=price_units)
                type_examples.setdefault(delta["type"], note)
                print(f"  [{b['date']}] DELTA [{delta['type']}] {note}")
                print(f"            old_ids={delta.get('old_ids')}  new_ids={delta.get('new_ids')}")
            if matched:
                matched["points"] = cap_points(matched["points"] + [point_of(fact)], traj)
                if vec is not None:
                    matched["embedding"] = vec
            else:
                mem.append({"label": _clean_label(story["label"]), "embedding": vec,
                            "points": [point_of(fact)]})
        print(f"  [{b['date']}] stories={len(stories)} threads={len(mem)} deltas={day_deltas}")
    print("\nOne example per delta type seen:")
    for t in ALL_DELTA_TYPES:
        print(f"  {t:12} {type_examples.get(t, '(none in this window)')}")
    print("\nVERIFY: every delta above lists old_ids vs new_ids (DB article UUIDs) — "
          "data-to-data per §4.3, never prose.")


def point_of(fact):
    return {"as_of": fact["as_of"], "value": fact["value"], "unit": fact.get("unit"),
            "short_fact": fact.get("short_fact"), "article_ids": fact["article_ids"],
            "delta_type": fact["delta_type"]}


def _load_articles(sb, ids):
    out = []
    ids = list(ids)
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        r = (sb.table("raw_articles")
             .select("id, title, content_raw, cluster_id, source_id, published_at")
             .in_("id", chunk).execute())
        out.extend(r.data or [])
    return out


def _fake_clusters(arts):
    """Group articles by cluster_id into pseudo-themes so brief_stories() can run in simulation."""
    by = {}
    for a in arts:
        by.setdefault(a.get("cluster_id") or a["id"], []).append(a)
    return list(by.values())


def _parse_ts(ts):
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone(timezone.utc)
    except (ValueError, TypeError):
        return datetime.now(timezone.utc)


def main():
    ap = argparse.ArgumentParser(description="NF-C1 sequencing (spec §4.4)")
    ap.add_argument("--simulate", action="store_true",
                    help="read-only 7-day replay: print data-to-data deltas, no writes")
    ap.add_argument("--days", type=int, default=7)
    args = ap.parse_args()
    if args.simulate:
        _simulate(args.days)
        return 0
    print("Use --simulate for a read-only verification run. Live sequencing is driven by the "
          "Writer when sequencing_enabled: true.")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    sys.exit(main())
