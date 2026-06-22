"""
NewsFramer WhatsApp briefs — multi-chat, topic-filtered, multi-language, posted via the `wikibot`
account. Driven by config/whatsapp_deliveries.yaml (gitignored registry). SEPARATE from the 06:00
Telegram brief: reuses the Writer's functions (writer.py untouched), passes EMPTY user-context
(no private hypotheses), and does NOT write to `briefings`.

Per chat in the registry: topic-based article selection (by analyst `topics`, NOT source), then a
full analytical brief. languages[0] is primary (carries sources); later languages are translated
from a source-stripped copy (cleaner + cheaper). DMs target an E.164 number; groups a saved JID.

Usage:  python run_whatsapp_brief.py              (dry run: generate + save + print, no send)
        python run_whatsapp_brief.py --send       (generate + save + post to every chat)
        python run_whatsapp_brief.py --send-saved  (post the saved files; no regeneration)
"""
import os
import re
import sys
import json
import argparse
import subprocess
import uuid

import yaml
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agents.writer import (  # noqa: E402  (reuse, do not modify writer.py)
    load_config, get_supabase, load_window_scored_articles, cluster_by_topic_overlap,
    pick_highlights, build_user_prompt, load_prompt_files, estimate_cost, JST,
)
from agents.deliver import record_delivered, send_alert  # noqa: E402  (§4.3 confirmed-send recording)
from agents.run_log import record_run  # noqa: E402  (NF-14: track WhatsApp-path LLM cost)
from agents.char_monitor import overrun_flag  # noqa: E402  (NF-F2: over-cap quality flag)
from agents.window_audit import window_span_report  # noqa: E402  (NF-NEW2: provable 24h window)
from agents import surface_render as srf  # noqa: E402  (2026-06-19: size/exclude/link/dedup)
from litellm import completion  # noqa: E402
from datetime import datetime, timezone, timedelta  # noqa: E402

try:  # Windows consoles default to cp1252 and crash printing Urdu script.
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = os.path.dirname(os.path.abspath(__file__))
OPENCLAW_MJS = os.environ.get(
    "OPENCLAW_MJS",
    os.path.join(os.environ.get("APPDATA", ""), "npm", "node_modules", "openclaw", "openclaw.mjs"),
)
TMP = os.environ.get("TEMP", BASE)
REGISTRY_PATH = os.path.join(BASE, "config", "whatsapp_deliveries.yaml")
LANG_LABELS = {"ur": "Urdu (Urdu script)", "ar": "Arabic", "hi": "Hindi", "en": "English"}
DEFAULT_TOPIC_KEYWORDS = {
    # NF-E5: broadened so genuinely geopolitical stories whose analyst topics use
    # rights / authoritarianism / migration language are no longer dropped. The
    # live registry (config/whatsapp_deliveries.yaml) may override this per deploy.
    "geopolitics": ["geopolit", "middle east", "international affairs", "foreign policy", "diplomacy",
                    "ceasefire", "sanction", "nato", "united nations", "security council",
                    "authoritarian", "human rights", "human trafficking", "refugee", "asylum",
                    "genocide", "war crime", "occupation", "coup", "press freedom"],
    "pakistan": ["pakistan", "kashmir", "balochistan"],
    "cybersecurity": ["cyber", "malware", "ransomware", "vulnerability", "exploit", "breach", "cve"],
}


def load_registry():
    if os.path.exists(REGISTRY_PATH):
        with open(REGISTRY_PATH, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


def out_file(chat, lang):
    safe = re.sub(r"[^a-z0-9]+", "_", chat.lower()).strip("_")
    return os.path.join(TMP, f"nf_wa_{safe}_{lang}.txt")


def md_to_whatsapp(text):
    out = []
    for line in text.split("\n"):
        m = re.match(r"^\s*#{1,6}\s+(.*)$", line)
        if m:
            out.append("*" + m.group(1).strip() + "*")
            continue
        s = re.sub(r"\*\*(.+?)\*\*", r"*\1*", line)
        s = re.sub(r"^\s*[-*]\s+", "• ", s)
        out.append(s)
    return "\n".join(out)


def strip_sources(text):
    """Drop the '*Articles:*' blocks, inline [n] markers, and [Label](url) links — for secondary langs."""
    lines, out, skip = text.split("\n"), [], False
    for line in lines:
        st = line.strip()
        if st.startswith("*Articles:*"):
            skip = True
            continue
        if skip:
            if st == "":
                skip = False
                out.append(line)
                continue
            if re.match(r"^\[\d+\]", st):
                continue
            skip = False
        out.append(line)
    t = "\n".join(out)
    t = re.sub(r"\s*\[\d+\]", "", t)
    t = re.sub(r"\s*\[[^\]]+\]\(https?://[^)]+\)", "", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def topic_match(article, categories, topic_keywords):
    """TOPIC-based: keep if any analyst topic contains a category keyword (NOT source-based)."""
    blob = " ".join(article["score"].get("topics") or []).lower()
    for cat in categories:
        for kw in topic_keywords.get(cat, [cat]):
            if kw.lower() in blob:
                return True
    return False


def is_fresh(published_at, now_utc, fresh_hours):
    """NF-C2: True if the article was published within the last `fresh_hours` (the gap
    since the previous slot). Pure + tolerant — a bad/blank timestamp is simply not fresh."""
    if not published_at or fresh_hours is None:
        return False
    try:
        p = datetime.fromisoformat(str(published_at).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return False
    if p.tzinfo is None:
        p = p.replace(tzinfo=timezone.utc)
    return p >= now_utc - timedelta(hours=int(fresh_hours))


def gap_refresh():
    """NF-C2: at the second daily slot, refresh the scored pool with the gap since the
    06:00 run — fetcher -> classifier -> deduplicator(--apply) -> analyst. Each engine is
    incremental (only new URLs / branch-null / unscored rows), so this just adds the
    06:00-11:00 news. Fully wrapped: any stage failure logs + continues, and the brief
    still builds from whatever is already scored (a refresh problem can never block it)."""
    base = os.path.dirname(os.path.abspath(__file__))
    py = sys.executable
    # NF-4 (§4.1): the second slot FETCHES only the gap since 06:00, not the full per-source window.
    # This env caps the fetcher's window (fetcher.source_window_hours); the 06:00 run_brief is a
    # separate process and is unaffected. 0/null => no cap (old full re-pull).
    try:
        gap_h = int(load_config().get("whatsapp_gap_fetch_hours", 6) or 0)
    except Exception:
        gap_h = 6
    if gap_h > 0:
        os.environ["NEWSFRAMER_MAX_FETCH_WINDOW_HOURS"] = str(gap_h)
        print(f"  [gap-refresh] fetch window capped to {gap_h}h (the gap since 06:00, §4.1)")
    stages = [
        ("fetcher",      [py, os.path.join(base, "agents", "fetcher.py")]),
        ("classifier",   [py, os.path.join(base, "agents", "classifier.py")]),
        ("deduplicator", [py, os.path.join(base, "agents", "deduplicator.py"), "--apply"]),
        ("analyst",      [py, os.path.join(base, "agents", "analyst.py")]),
    ]
    # NF-NEW10: collapse same-story wire copies before the analyst, only when enabled (default off).
    try:
        if load_config().get("title_dedup_enabled", False):
            _ai = next(i for i, (n, _) in enumerate(stages) if n == "analyst")
            stages.insert(_ai, ("title_dedup", [py, os.path.join(base, "agents", "title_dedup.py"), "--apply"]))
    except Exception:
        pass
    for name, cmd in stages:
        try:
            print(f"  [gap-refresh] {name} ...")
            r = subprocess.run(cmd, cwd=base, timeout=int(load_config().get("whatsapp_gap_stage_timeout_seconds", 1800)))
            if r.returncode != 0:
                print(f"  [gap-refresh] {name} exit {r.returncode} — continuing (brief uses existing scores).")
        except Exception as e:
            print(f"  [gap-refresh] {name} EXCEPTION {type(e).__name__}: {e} — continuing.")


def _usage_tokens(resp):
    """(prompt_tokens, completion_tokens) from an LLM response, (0, 0) if absent. Pure."""
    usage = getattr(resp, "usage", None)
    if not usage:
        return (0, 0)
    return (getattr(usage, "prompt_tokens", 0) or 0, getattr(usage, "completion_tokens", 0) or 0)


def _record_llm_cost(sb, config, agent_name, model, resp, status="success"):
    """NF-14: log a WhatsApp-path LLM call's real cost to agent_runs + execution_log, so the
    group/Muda generation + translation are no longer invisible. Best-effort via record_run;
    main's trace_id ties them to the run. Returns the cost (USD)."""
    t_in, t_out = _usage_tokens(resp)
    cost = estimate_cost(config, model, t_in, t_out)
    record_run(sb, {"agent_name": agent_name, "model_used": model, "tokens_in": t_in,
                    "tokens_out": t_out, "cost_usd": round(cost, 6), "status": status})
    return cost


def _send_timeout():
    """Per-message gateway send timeout (config-driven; cached). Default 120s."""
    global _SEND_TIMEOUT
    if _SEND_TIMEOUT is None:
        try:
            _SEND_TIMEOUT = int(load_config().get("whatsapp_send_timeout_seconds", 120))
        except Exception:
            _SEND_TIMEOUT = 120
    return _SEND_TIMEOUT


_SEND_TIMEOUT = None


def resolve_length(config, length):
    """item 3 (2026-06-22): a chat's `length` (short/medium/long, or None) maps onto the ONE size
    model via config['length_to_size'] (short=S / medium=M / long=L) and OVERRIDES the whatsapp
    surface theme_size; None -> the surface theme_size. Theme counts / articles-per-theme come from
    the global writer_* values. Pure / config-driven (the per-theme char TARGET drives length)."""
    size = srf.resolve_size_level(config, "whatsapp", chat_length=length)
    return {
        "level": length or config.get("default_length", "medium"),
        "size": size,
        "min_rel": int(config.get("writer_min_relevance", 6)),
        "rel_floor": int(config.get("writer_relevance_floor", 4)),
        "max_themes": int(config.get("writer_max_themes", 5)),
        "min_themes": int(config.get("writer_min_themes", 3)),
        "max_per_theme": int(config.get("writer_max_articles_per_theme", 6)),
        "per_theme_target": srf.per_theme_target(config, size),
    }


def generate_brief(config, sb, categories, topic_keywords, length=None, exclude_keywords=None):
    """Returns (briefing_text, model_used, selected_ids) or (None, None, []) when nothing qualifies.
    `length` (short/medium/long, NF-E2) selects the brief-shape knobs via resolve_length (default
    => medium => today's behaviour). `exclude_keywords` (item 5, 2026-06-19) is the per-category
    negative topic filter that drops crypto/markets leaks; None => include-only (today's behaviour)."""
    model = config.get("writer_model", "anthropic/claude-haiku-4-5")
    fallback_model = config.get("writer_fallback_model", "gemini/gemini-2.5-flash-lite")
    window_hours = int(config.get("writer_window_hours", 24))
    L = resolve_length(config, length)
    min_rel, rel_floor = L["min_rel"], L["rel_floor"]
    max_themes, min_themes = L["max_themes"], L["min_themes"]
    max_per_theme = L["max_per_theme"]
    per_theme_goal = L["per_theme_target"]
    per_highlight_chars = int(config.get("writer_per_highlight_chars", 250))
    print(f"  size {L['size']} (len={L['level']}) -> ~{per_theme_goal} chars/theme target, max_themes={max_themes}")

    candidates, _total = load_window_scored_articles(sb, window_hours, exclude_account=None)
    r = sb.table("sources").select("id, name").execute()
    sources_map = {s["id"]: s.get("name", "Unknown") for s in (r.data or [])}
    # item 5 (2026-06-19): include match AND per-category exclude (drops crypto/markets leaks that
    # the analyst tagged 'geopolitics affecting markets'). exclude_keywords None => include-only.
    cand = [a for a in candidates if srf.passes_topic_filter(
        a["score"].get("topics"), categories, topic_keywords, exclude_keywords)]
    print(f"  in-window scored: {len(candidates)} | topic-match {categories} (excludes on): {len(cand)}")
    # NF-NEW2: prove the refreshed-topic set really spans ~24h (existing ~19h + the 06:00->11:00 gap).
    _fresh_h = int(config.get("whatsapp_fresh_hours", 6))
    print("  " + window_span_report([a.get("published_at") for a in cand],
                                     window_hours, datetime.now(timezone.utc), _fresh_h,
                                     label=f"WINDOW {categories}"))

    def over(a, rel):
        s = a["score"]
        return (s.get("relevance_score") or 0) >= rel or (s.get("actionability") or 0) >= 2

    articles, chosen = [], min_rel
    for rel in range(min_rel, rel_floor - 1, -1):
        chosen = rel
        articles = [a for a in cand if over(a, rel)]
        if len(articles) >= min_themes:
            break
    # NF-C2 weight-fresh-higher: admit articles published in the last `whatsapp_fresh_hours`
    # at the relevance FLOOR (not the higher day threshold), so genuinely new stories from the
    # gap-refresh surface even if borderline — without lowering the bar for the whole day.
    fresh_hours = int(config.get("whatsapp_fresh_hours", 6))
    now_utc = datetime.now(timezone.utc)
    chosen_ids = {a["id"] for a in articles}
    fresh_extra = [a for a in cand if a["id"] not in chosen_ids
                   and is_fresh(a.get("published_at"), now_utc, fresh_hours) and over(a, rel_floor)]
    if fresh_extra:
        articles = articles + fresh_extra
        print(f"  NF-C2: +{len(fresh_extra)} fresh (<{fresh_hours}h) article(s) admitted at the floor")
    print(f"  qualifying (rel>={chosen} or act>=2, +fresh@floor): {len(articles)}")
    if not articles:
        return None, None, []
    quiet = len(articles) < min_themes

    clusters, leftovers = cluster_by_topic_overlap(articles, max_themes, max_per_theme)
    if not clusters:
        return None, None, []
    # item 6 (2026-06-22): per-category theme cap for WhatsApp — assign each cluster its majority
    # SOURCE category (the same cluster_bundle logic Telegram uses) and keep <= cap themes per
    # category; over-cap clusters are demoted to the highlights pool. Config-driven; 0/absent = no cap.
    _cap = int(((config.get("surfaces") or {}).get("whatsapp") or {}).get("per_category_theme_cap", 0) or 0)
    if _cap > 0 and clusters:
        from agents.bundle_floors import cluster_bundle
        _src_cat = {s["id"]: s.get("category")
                    for s in (sb.table("sources").select("id, category").execute().data or [])}
        _kept, _per, _dropped = [], {}, []
        for _cl in clusters:   # already best-first by composite score
            _b = cluster_bundle(_cl, _src_cat)
            if _b is not None and _per.get(_b, 0) >= _cap:
                _dropped.append(_cl)
            else:
                if _b is not None:
                    _per[_b] = _per.get(_b, 0) + 1
                _kept.append(_cl)
        if _dropped:
            leftovers = leftovers + [a for _cl in _dropped for a in _cl]
            print(f"  WA per-category cap {_cap}: kept {len(_kept)}/{len(clusters)} themes "
                  f"(demoted {len(_dropped)} over-cap cluster(s) to highlights).")
        clusters = _kept
    highlights = pick_highlights(
        leftovers, int(config.get("writer_highlights_count", 8)),
        int(config.get("writer_highlights_min_relevance", 8)),
    )
    # item 3 (2026-06-19): collapse repetitive highlights (same event/topic) — same machinery as
    # the Telegram brief. Config-gated; default reproduces today's set when nothing is duplicate.
    if config.get("highlight_dedup_enabled", True):
        _theme_arts = [a for cl in clusters for a in cl]
        _hb = len(highlights)
        highlights = srf.dedupe_highlights(
            highlights, _theme_arts,
            by_cluster=bool(config.get("highlight_dedup_by_cluster", True)),
            topic_overlap=float(config.get("highlight_dedup_topic_overlap", 1.0)),
            min_shared_topics=int(config.get("highlight_dedup_min_shared_topics", 3)))
        if len(highlights) != _hb:
            print(f"  highlight dedup: {_hb} -> {len(highlights)} (same event/topic collapsed)")
    selected_ids = list(dict.fromkeys(
        [a["id"] for cl in clusters for a in cl] + [h["id"] for h in highlights]
    ))
    max_chars = srf.derive_cap(per_theme_goal, len(clusters),
                               int(config.get("writer_highlights_count", 8)), per_highlight_chars,
                               int(config.get("writer_per_theme_source_chars", 500)))
    # item 1/2 (2026-06-22): scale the output-token budget with the cap so a larger size isn't truncated.
    _wa_max_tokens = min(int(config.get("writer_max_output_tokens_ceiling", 8000)),
                         max(int(config.get("whatsapp_max_tokens", 4500)), max_chars // 3 + 500))
    briefing_date = datetime.now(JST).strftime("%Y-%m-%d (%H:%M JST)")
    system_prompt = load_prompt_files()
    empty_ctx = {"interests": [], "hypotheses": [], "by_id": {}}
    user_prompt = build_user_prompt(
        clusters, highlights, sources_map, {}, empty_ctx,
        len(cand), len(articles), briefing_date, max_chars, per_theme_target=per_theme_goal,
        chars_per_paragraph=int(config.get("writer_chars_per_paragraph", 1000)),
    )
    msgs = [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]
    used = model
    print(f"  generating with {model} ({len(clusters)} themes, {len(highlights)} highlights)...")
    try:
        resp = completion(model=model, messages=msgs, temperature=float(config.get("whatsapp_temperature", 0.3)), max_tokens=_wa_max_tokens)
    except Exception as e:
        if fallback_model and fallback_model != model:
            print(f"  PRIMARY {model} failed ({e}); falling back to {fallback_model}")
            used = fallback_model
            resp = completion(model=used, messages=msgs, temperature=float(config.get("whatsapp_temperature", 0.3)), max_tokens=_wa_max_tokens)
        else:
            raise
    text = resp.choices[0].message.content.strip()
    if quiet:
        text = "_Quiet news day — fewer items than usual._\n\n" + text
    # NF-F2: flag (don't fail) an over-cap brief so editorial drift is visible in the run log.
    print(f"  brief chars: {len(text)} (cap {max_chars})")
    _overrun = overrun_flag(len(text), max_chars, config.get("writer_char_overrun_warn_ratio", 1.0))
    if _overrun:
        print(f"  {_overrun}")
    _record_llm_cost(sb, config, "whatsapp_writer", used, resp)  # NF-14: track the group/DM gen cost
    return text, used, selected_ids


def translate(config, text, lang, translate_model, sb=None):
    label = LANG_LABELS.get(lang, lang)
    fallback = config.get("writer_model", "anthropic/claude-haiku-4-5")
    sys_p = (
        f"You are a professional translator. Translate the user's English news brief into natural, "
        f"fluent {label}. Preserve the structure EXACTLY: same headings, bullets (•), bold (*...*) "
        f"markers, and the final footer line. Keep proper nouns and organisation names in English "
        f"(do not transliterate names). Output ONLY the translation — no preamble, no notes."
    )
    msgs = [{"role": "system", "content": sys_p}, {"role": "user", "content": text}]
    used = translate_model
    try:
        resp = completion(model=translate_model, messages=msgs, temperature=float(config.get("whatsapp_translate_temperature", 0.2)), max_tokens=int(config.get("whatsapp_translate_max_tokens", 6000)))
    except Exception as e:
        print(f"  translate {translate_model} failed ({e}); falling back to {fallback}")
        used = fallback
        resp = completion(model=used, messages=msgs, temperature=float(config.get("whatsapp_translate_temperature", 0.2)), max_tokens=int(config.get("whatsapp_translate_max_tokens", 6000)))
    if sb is not None:
        _record_llm_cost(sb, config, "whatsapp_translate", used, resp)  # NF-14: track translation cost
    return resp.choices[0].message.content.strip(), used


def send_whatsapp(text, account, target):
    cmd = ["node", OPENCLAW_MJS, "message", "send", "--channel", "whatsapp",
           "--account", account, "--target", target, "--message", text, "--json"]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=_send_timeout())
    return r.returncode, (r.stdout or "")[-400:], (r.stderr or "")[-200:]


def confirmed_message_id(rc, stdout):
    """A send is confirmed only if rc==0 AND the gateway returned a real messageId."""
    if rc != 0:
        return None
    m = re.search(r'"messageId"\s*:\s*"?([^",}\s]+)', stdout or "")
    return m.group(1) if m else None


def maybe_send_worldcup(reg):
    """Append the World Cup message to the 11:00 dispatch (user-approved 2026-06-15).
    Runs AFTER the main WhatsApp brief has already sent, and is fully wrapped: any WC
    failure (fetch/parse/build/send) is caught + alerted and can NEVER affect the main
    brief. Self-skips when empty or after the tournament ends. Sends to the same chats
    the registry feeds (group + Muda's DM), minus any with `worldcup: false`."""
    try:
        import run_worldcup_brief as wc  # imports worldcup_data/format + deliver only (no litellm)
        cfg = load_config()
        end = cfg.get("worldcup_end_date", "2026-07-19")
        now = datetime.now(JST)
        if now.date().isoformat() > end:
            print("  WC: tournament ended; skip.")
            return
        html = wc.wd.fetch()
        pay, msg = wc.build(html, now, cfg)
        why = wc.skip_reason(pay, now, end)
        if why:
            print(f"  WC: skip (no empty send) — {why}.")
            return
        confirmed, attempted = wc.deliver(msg, reg)
        print(f"  WC: {confirmed}/{attempted} target(s) confirmed.")
    except Exception as e:
        print(f"  WC: skipped (isolated failure) — {type(e).__name__}: {e}")
        try:
            send_alert(f"⚠️ NewsFramer WC (11:00 dispatch): {type(e).__name__} — "
                       f"WC message skipped; the main WhatsApp brief is unaffected.")
        except Exception:
            pass


def maybe_send_football(reg):
    """Append the Football news message to the 11:00 dispatch (NF-A2). Config-gated
    (football_enabled, default false => no-op). Fully isolated: any failure is caught +
    alerted and can NEVER affect the main brief or the World Cup message. Self-skips when
    nothing is in the window (no empty send). Sends to the same chats the registry feeds
    (group + Muda's DM), minus any with `football: false`."""
    try:
        cfg = load_config()
        if not cfg.get("football_enabled", False):
            print("  Football: disabled (football_enabled=false) — skip.")
            return
        import run_football_brief as fb  # event_feed + deliver only (no litellm)
        msg = fb.build_from_config(cfg)
        if not msg:
            print("  Football: skip (nothing in window).")
            return
        confirmed, attempted = fb.deliver(msg, reg)
        print(f"  Football: {confirmed}/{attempted} target(s) confirmed.")
    except Exception as e:
        print(f"  Football: skipped (isolated failure) — {type(e).__name__}: {e}")
        try:
            send_alert(f"⚠️ NewsFramer Football (11:00 dispatch): {type(e).__name__} — "
                       f"football message skipped; the main WhatsApp brief is unaffected.")
        except Exception:
            pass


def maybe_send_blindspot(reg):
    """Append the Blindspot-of-the-day message to the 11:00 dispatch (NF-D2). Gated by
    blindspot_enabled AND blindspot_whatsapp (default master-off => no-op). Fully isolated:
    any failure is caught + alerted and can NEVER affect the main brief, World Cup, or football
    message. Self-skips when nothing strong today. Sends to registry chats not opted out
    (`blindspot: false`)."""
    try:
        cfg = load_config()
        if not (cfg.get("blindspot_enabled", False) and cfg.get("blindspot_whatsapp", True)):
            print("  Blindspot: disabled — skip.")
            return
        from agents.blindspot import build_from_config as _bs_build
        block = _bs_build(cfg)
        if not block:
            print("  Blindspot: skip (nothing strong today).")
            return
        account = reg.get("account", "wikibot")
        targets = [d for d in reg.get("deliveries", []) if d.get("blindspot", True) and d.get("target")]
        confirmed = 0
        for d in targets:
            rc, o, e = send_whatsapp(block, account, d["target"])
            mid = confirmed_message_id(rc, o)
            print(f"  [Blindspot -> {d.get('name', '?')}] rc={rc} messageId={mid}")
            if mid:
                confirmed += 1
            else:
                send_alert(f"🚨 NewsFramer Blindspot: WhatsApp send FAILED for {d.get('name', '?')} (rc={rc}).")
        print(f"  Blindspot: {confirmed}/{len(targets)} target(s) confirmed.")
    except Exception as e:
        print(f"  Blindspot: skipped (isolated failure) — {type(e).__name__}: {e}")
        try:
            send_alert(f"⚠️ NewsFramer Blindspot (11:00 dispatch): {type(e).__name__} — "
                       f"blindspot message skipped; the main WhatsApp brief is unaffected.")
        except Exception:
            pass


def maybe_send_cost_report(reg):
    """After the WhatsApp dispatch reaches the group + Muda, send the OPERATOR (Telegram) a cost
    rollup for the whole day — the Telegram brief + every WhatsApp chat. Gated by
    cost_report_enabled; fully isolated. The chat list is read from the registry (dynamic — never
    hard-coded to a fixed number of groups), so adding chats later is automatic."""
    try:
        cfg = load_config()
        if not cfg.get("cost_report_enabled", False):
            return
        from agents.cost_report import build_and_send
        build_and_send(get_supabase(), reg, cfg, send_alert)
        print("  Cost report sent to the operator's Telegram.")
    except Exception as e:
        print(f"  Cost report skipped (isolated): {type(e).__name__}: {e}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true", help="generate, save, and post to every chat")
    ap.add_argument("--send-saved", action="store_true", help="post the saved files (no regeneration)")
    args = ap.parse_args()

    config = load_config()
    # NF-14: one trace_id ties this WhatsApp run's gap-refresh engines + LLM calls together in execution_log.
    os.environ["NEWSFRAMER_TRACE_ID"] = uuid.uuid4().hex
    os.environ["NEWSFRAMER_TASK_TYPE"] = "whatsapp_brief"
    reg = load_registry()
    account = reg.get("account", "wikibot")
    translate_model = reg.get("translate_model", config.get("whatsapp_translate_model", "gemini/gemini-2.5-flash-lite"))
    topic_keywords = reg.get("topic_keywords", DEFAULT_TOPIC_KEYWORDS)
    # item 5 (2026-06-19): per-category EXCLUDE list — registry override, else the config default
    # (the "loose" crypto/prediction-market list). {} => no exclusions (today's include-only).
    exclude_keywords = reg.get("topic_exclude_keywords", config.get("whatsapp_topic_exclude_keywords", {}))
    deliveries = reg.get("deliveries", [])
    if not deliveries:
        print(f"No deliveries configured in {REGISTRY_PATH}")
        return 2

    if args.send_saved:
        ok = True
        for d in deliveries:
            for lang in d["languages"]:
                p = out_file(d["name"], lang)
                if not os.path.exists(p):
                    print(f"  MISSING {p} — run a dry run first."); ok = False; continue
                rc, o, e = send_whatsapp(open(p, encoding="utf-8").read(), account, d["target"])
                print(f"  [{d['name']}/{lang}] rc={rc} {o} {e}")
                ok = ok and rc == 0
        print("\nALL SENT OK." if ok else "\nWARN: a send failed.")
        return 0 if ok else 1

    # NF-C2: on a real send, refresh the pool with the gap since 06:00 so this slot is
    # genuinely fresh (not a re-filtered copy of the morning). Skipped on dry runs.
    if args.send and config.get("whatsapp_gap_refresh", True):
        print("\n=== NF-C2 gap-refresh (fetch -> classify -> dedup -> analyst since the 06:00 run) ===")
        gap_refresh()

    sb = get_supabase()
    default_length = config.get("default_length", "medium")
    cache = {}  # (frozenset(categories), length) -> (text, model, ids)
    any_posted = False
    for d in deliveries:
        name, target, langs, cats = d["name"], d["target"], d["languages"], d["categories"]
        length = d.get("length")   # None -> the whatsapp surface theme_size (item 3)
        print(f"\n=== {name} ({d.get('kind','?')}) | cats={cats} | langs={langs} | len={length or 'default'} | -> {target} ===")
        key = (frozenset(cats), length)
        if key not in cache:
            cache[key] = generate_brief(config, sb, cats, topic_keywords, length=length,
                                        exclude_keywords=exclude_keywords)
        en, used, ids = cache[key]
        if en is None:
            print(f"  QUIET — nothing qualifies for {name}; skipping.")
            continue
        wa_cfg = srf.link_cfg(config, "whatsapp")
        # item 2 (2026-06-19): the PRIMARY language carries TITLE + SOURCE only (no link/URL) —
        # replacing the literal '[Source](url)' markdown WhatsApp can't render. Secondary languages
        # keep today's behaviour (source list stripped from the canonical copy before translating).
        en_full = md_to_whatsapp(srf.render_citations(en, wa_cfg, number_style="none"))
        en_strip = strip_sources(md_to_whatsapp(en))
        # item 7 (2026-06-22): secondary (non-primary) languages drop the source list by DEFAULT
        # (include_sources_in_secondary_language=false = current behaviour); set true to carry
        # TITLE+SOURCE into the secondary language(s) too. The PRIMARY (i==0) path is untouched.
        secondary_base = en_full if config.get("include_sources_in_secondary_language", False) else en_strip
        chat_ok = True  # did EVERY send for this chat confirm a messageId?
        for i, lang in enumerate(langs):
            base = en_full if i == 0 else secondary_base
            text = base if lang == "en" else translate(config, base, lang, translate_model, sb)[0]
            with open(out_file(name, lang), "w", encoding="utf-8") as f:
                f.write(text)
            print(f"  [{name}/{lang}] {len(text)} chars -> {out_file(name, lang)}")
            if args.send:
                rc, o, e = send_whatsapp(text, account, target)
                mid = confirmed_message_id(rc, o)
                print(f"    SENT rc={rc} messageId={mid} {o}")
                if mid:
                    any_posted = True
                else:
                    chat_ok = False
                    send_alert(f"🚨 NewsFramer: WhatsApp send FAILED for {name}/{lang} "
                               f"(rc={rc}) — recorded NOTHING for {name}.")
        # §4.3: record this chat's delivered article_ids ONLY if EVERY send confirmed.
        if args.send and chat_ok and ids:
            n = record_delivered(sb, f"whatsapp:{name}", ids, None)
            print(f"  recorded {n} delivered article_id(s) for whatsapp:{name}")
        elif args.send and not chat_ok:
            print(f"  NOT recorded for {name} (a send failed; alerted).")
    # World Cup message — a SEPARATE WhatsApp message appended to this same dispatch,
    # isolated so it can never affect the main brief above (only on a real --send).
    if args.send:
        print("\n=== World Cup message (appended, isolated) ===")
        maybe_send_worldcup(reg)
        print("\n=== Football news message (appended, isolated) ===")
        maybe_send_football(reg)
        print("\n=== Blindspot of the day (appended, isolated) ===")
        maybe_send_blindspot(reg)
        print("\n=== Cost report (after the dispatch reached the group + Muda) ===")
        maybe_send_cost_report(reg)
    if not args.send:
        print("\nDRY RUN — nothing sent. Re-run with --send (or --send-saved to post the saved files).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
