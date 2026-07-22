"""
setup_check.py — NewsFramer "doctor". Verifies a fresh install is wired up correctly, BEFORE you
try a real brief. It probes, in order:

  1. .env present and the required variables are set (reports NAMES only — never a value).
  2. Supabase reachable with your URL + service key.
  3. The expected tables exist (the 10 defined in sql/schema.sql).
  4. The `sources` table has at least one row (did you run sql/seed_sources.sql?).
  5. One real RSS fetch (BBC World) returns entries.
  6. Your LLM key works — a 1-token Gemini call. Skip this last one with --offline.

Each probe prints PASS or FAIL with a short reason. Secrets are NEVER printed. Exit code is 0 only
if every run probe passed.

    venv\\Scripts\\python.exe setup_check.py            # full check
    venv\\Scripts\\python.exe setup_check.py --offline  # skip the network + LLM probes (5 and 6)
"""
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

OFFLINE = "--offline" in sys.argv

ROOT = os.path.dirname(os.path.abspath(__file__))

# The tables sql/schema.sql creates (must match it).
EXPECTED_TABLES = [
    "sources", "raw_articles", "analyst_scores", "briefings", "deliveries",
    "junk_patterns", "user_context", "agent_runs", "execution_log", "tracked_threads",
]
REQUIRED_ENV = ["SUPABASE_URL", "SUPABASE_SERVICE_KEY", "GEMINI_API_KEY",
                "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]
OPTIONAL_ENV = ["ANTHROPIC_API_KEY", "FIRECRAWL_API_KEY"]

results = []  # (name, passed, detail)


def record(name, passed, detail=""):
    results.append((name, passed, detail))
    tag = "PASS" if passed else "FAIL"
    line = f"[{tag}] {name}"
    if detail:
        line += f" — {detail}"
    print(line)


def _cheap_model():
    """Read a cheap Gemini model id from config/models.yaml; fall back to a sane default."""
    default = "gemini/gemini-2.5-flash-lite"
    try:
        import yaml
        with open(os.path.join(ROOT, "config", "models.yaml"), encoding="utf-8") as fh:
            cfg = yaml.safe_load(fh) or {}
        m = cfg.get("classifier_model") or cfg.get("analyst_model") or default
        return m
    except Exception:
        return default


def probe_env():
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(ROOT, ".env"))
    except Exception as e:
        record("1. .env / required vars", False, f"could not load dotenv: {type(e).__name__}")
        return
    missing = [k for k in REQUIRED_ENV if not os.getenv(k)]
    opt_missing = [k for k in OPTIONAL_ENV if not os.getenv(k)]
    if missing:
        record("1. .env / required vars", False, "missing (names only): " + ", ".join(missing))
    else:
        note = "all required set"
        if opt_missing:
            note += "; optional not set: " + ", ".join(opt_missing)
        record("1. .env / required vars", True, note)


def _client():
    from supabase import create_client
    url, key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_KEY")
    if not url or not key:
        return None
    return create_client(url, key)


def probe_supabase_and_tables():
    sb = None
    try:
        sb = _client()
    except Exception as e:
        record("2. Supabase reachable", False, f"{type(e).__name__}")
    if sb is None:
        record("2. Supabase reachable", False, "SUPABASE_URL / SUPABASE_SERVICE_KEY not set")
        record("3. Expected tables exist", False, "skipped (no client)")
        record("4. sources has rows", False, "skipped (no client)")
        return

    # Probe 2 + 3: query each expected table for a single row.
    present, sources_count = [], None
    reachable = False
    for t in EXPECTED_TABLES:
        try:
            resp = sb.table(t).select("id", count="exact").limit(1).execute()
            reachable = True
            present.append(t)
            if t == "sources":
                sources_count = resp.count if resp.count is not None else len(resp.data or [])
        except Exception:
            pass
    record("2. Supabase reachable", reachable,
           "connected" if reachable else "no table query succeeded — check URL/key")
    missing = [t for t in EXPECTED_TABLES if t not in present]
    record("3. Expected tables exist", not missing,
           f"{len(present)}/{len(EXPECTED_TABLES)} present"
           + (f"; missing: {', '.join(missing)}" if missing else ""))

    # Probe 4: sources row count.
    if sources_count is None:
        try:
            resp = sb.table("sources").select("id", count="exact").limit(1).execute()
            sources_count = resp.count if resp.count is not None else len(resp.data or [])
        except Exception as e:
            record("4. sources has rows", False, f"{type(e).__name__}")
            return
    record("4. sources has rows", (sources_count or 0) > 0, f"{sources_count} source(s)")


def probe_rss():
    if OFFLINE:
        record("5. RSS fetch (BBC World)", True, "skipped (--offline)")
        return
    url = "http://feeds.bbci.co.uk/news/world/rss.xml"
    try:
        import requests
        import feedparser
        r = requests.get(url, timeout=20, headers={"User-Agent": "NewsFramer-setup-check"})
        feed = feedparser.parse(r.content)
        n = len(feed.entries or [])
        record("5. RSS fetch (BBC World)", n > 0, f"{n} entries")
    except Exception as e:
        record("5. RSS fetch (BBC World)", False, f"{type(e).__name__}: {e}")


def probe_llm():
    if OFFLINE:
        record("6. LLM key (Gemini)", True, "skipped (--offline)")
        return
    if not os.getenv("GEMINI_API_KEY"):
        record("6. LLM key (Gemini)", False, "GEMINI_API_KEY not set")
        return
    model = _cheap_model()
    try:
        from litellm import completion
        resp = completion(model=model,
                          messages=[{"role": "user", "content": "Reply with the single word: ok"}],
                          max_tokens=1)
        got = bool(resp and resp.choices)
        record("6. LLM key (Gemini)", got, f"model {model} responded" if got else "empty response")
    except Exception as e:
        record("6. LLM key (Gemini)", False, f"{type(e).__name__}: {e}")


def main():
    print("NewsFramer setup check" + ("  (offline mode)" if OFFLINE else ""))
    print("-" * 48)
    probe_env()
    probe_supabase_and_tables()
    probe_rss()
    probe_llm()
    print("-" * 48)
    failed = [n for (n, ok, _) in results if not ok]
    if failed:
        print(f"{len(results) - len(failed)}/{len(results)} passed. FIX: " + "; ".join(failed))
        return 1
    print(f"All {len(results)} probes passed. You're ready: try  python run_brief.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
