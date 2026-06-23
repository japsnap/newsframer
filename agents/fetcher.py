"""
OpenClaw Fetcher Agent
----------------------
Fetches articles from all active sources in Supabase.
Priority sources (vc_blog, research, blog) are always fetched first and guaranteed.
News sources are fetched based on weight and total article limits.
"""

import feedparser
import requests
import yaml
import os
import sys
import time
import hashlib
import random
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup
from supabase import create_client
from dotenv import load_dotenv

from run_log import record_run

load_dotenv()

# Windows cp1252 consoles crash printing non-Latin titles (global feeds) — make stdout
# UTF-8 so logging a source/article can never kill the run (2026-06-16 smoke-test incident).
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# Sources that errored during this run (fetch_rss / fetch_web swallow per-source
# errors so one bad feed can't sink the rest). Reset per run by run_fetcher;
# used to report an honest agent_runs status instead of always "success".
FETCH_ERRORS = []

# §8.7: the distributed scrape calendar is keyed to the JST weekday (the brief runs 06:00 JST).
JST = timezone(timedelta(hours=9))

# --- Config ---
def load_config():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(base_dir, "config", "models.yaml")
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


try:  # module-level read for the helpers that don't receive `config` (wrapped -> defaults)
    _CFG = load_config() or {}
except Exception:
    _CFG = {}
PR_KEYWORDS = list(_CFG.get("fetcher_pr_keywords", ["sponsored", "partner", "press release", "advertorial", "paid post"]))
SCRAPE_TIMEOUT = int(_CFG.get("fetcher_scrape_timeout_seconds", 10))

# --- Supabase ---
def get_supabase():
    return create_client(
        os.getenv("SUPABASE_URL"),
        os.getenv("SUPABASE_SERVICE_KEY")
    )

# --- Helpers ---
def get_cutoff_time(config, is_first_run=False):
    hours = config.get("first_run_hours_back", 48) if is_first_run else config.get("fetch_hours_back", 24)
    return datetime.now(timezone.utc) - timedelta(hours=hours)

def source_window_hours(config, source, is_first_run):
    """§8.1: each source uses its OWN fetch_window_hours; fall back to the global default.
    NF-4 (§4.1 incremental fetch): the 11:00 gap-refresh sets NEWSFRAMER_MAX_FETCH_WINDOW_HOURS to
    the gap since the 06:00 slot, which CAPS the window here — so the second slot fetches only the
    new ~5-6h of content instead of re-pulling the full day. Unset (the 06:00 run, a separate
    process) => the full per-source window, unchanged."""
    default_h = config.get("first_run_hours_back", 48) if is_first_run else config.get("fetch_hours_back", 24)
    win = source.get("fetch_window_hours") or default_h
    if is_first_run:
        win = max(win, config.get("first_run_hours_back", 48))
    cap = os.environ.get("NEWSFRAMER_MAX_FETCH_WINDOW_HOURS")
    if cap:
        try:
            win = min(win, int(cap))
        except (TypeError, ValueError):
            pass
    return win

def is_scrape_source(source):
    """A source is a scrape job when it has no usable RSS feed (routed to fetch_web)."""
    return not (source.get("has_rss") and source.get("rss_url"))

def scrape_scheduled_today(source, today_jst):
    """§8.7: gate heavy/scrape sources to their scheduled weekday(s). Null scrape_days = run whenever active."""
    sd = (source.get("scrape_days") or "").strip().lower()
    if not sd:
        return True
    return today_jst in [d.strip()[:3] for d in sd.split(",") if d.strip()]

def fetch_one(config, source, is_first_run, today_jst, limit):
    """Fetch one source honoring §8.1 per-source window + §8.7 scrape-day calendar.
    Returns (articles_or_None, status_note); None means skipped by the calendar.

    NF-A1(b): the `scrape_days` calendar now gates EVERY source, RSS included (it used to
    apply only to scrape sources), so a low-cadence RSS source like the Wed+Sat VC blogs is
    fetched only on its days. A null/blank `scrape_days` still means 'run whenever active',
    so all the daily sources are unaffected."""
    if not scrape_scheduled_today(source, today_jst):
        return None, f"skipped (scrape_days={source.get('scrape_days')}, today={today_jst})"
    win = source_window_hours(config, source, is_first_run)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=win)
    if source.get("has_rss") and source.get("rss_url"):
        arts = fetch_rss(source, cutoff, limit)
    else:
        arts = fetch_web(source, cutoff, limit)
    return arts, f"window {win}h -> {len(arts)} articles"

def is_pr_article(title: str, source: dict) -> bool:
    if source.get("notes") and "Avoid PR articles" in source["notes"]:
        return any(kw in title.lower() for kw in PR_KEYWORDS)
    return False

def load_junk_patterns(sb):
    """Load active junk patterns from DB"""
    try:
        result = sb.table("junk_patterns").select("*").eq("active", True).execute()
        return result.data
    except Exception:
        return []

def is_junk_url(url: str, title: str, patterns: list = None) -> bool:
    """Filter out non-article URLs"""
    if not url or not title:
        return True
    if len(url) < 30 or len(title) < 15:
        return True
    if not url.startswith("http"):
        return True

    url_lower = url.lower()
    title_lower = title.lower()

    if patterns:
        for p in patterns:
            pattern = p["pattern"].lower()
            ptype = p["pattern_type"]
            if ptype == "url_contains" and pattern in url_lower:
                return True
            if ptype == "url_endswith" and url_lower.endswith(pattern):
                return True
            if ptype == "title_contains" and pattern in title_lower:
                return True

    return False

def is_duplicate(sb, url: str, title: str) -> bool:
    result = sb.table("raw_articles").select("id").eq("url", url).execute()
    if result.data:
        return True
    return False

def url_hash(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()

# --- RSS Fetcher ---
def fetch_rss(source: dict, cutoff: datetime, max_articles: int) -> list:
    # item 5 (2026-06-22): scan ALL in-window entries, then keep the NEWEST `max_articles` by
    # published_at — RSS feed order is not always newest-first, so taking the top-N raw could drop
    # newer stories. Entries with no date default to now() (treated as newest), as before.
    candidates = []
    try:
        feed = feedparser.parse(source["rss_url"])
        for entry in feed.entries:
            title = entry.get("title", "")
            url = entry.get("link", "")

            if not title or not url:
                continue
            if is_pr_article(title, source):
                continue

            published = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)

            if published and published < cutoff:
                continue

            content = entry.get("summary", "") or entry.get("description", "")
            sort_dt = published or datetime.now(timezone.utc)
            candidates.append((sort_dt, {
                "source_id": source["id"],
                "title": title,
                "url": url,
                "content_raw": content[:5000],
                "published_at": (published.isoformat() if published else datetime.now(timezone.utc).isoformat()),
                "branch": None,
                "duplicate_count": 1,
            }))

    except Exception as e:
        FETCH_ERRORS.append(source.get("name", source.get("id", "?")))
        print(f"  RSS error for {source['name']}: {e}")
        return []

    candidates.sort(key=lambda t: t[0], reverse=True)   # newest-first
    return [art for _, art in candidates[:max_articles]]

# --- Web Scraper ---
def fetch_web(source: dict, cutoff: datetime, max_articles: int) -> list:
    articles = []
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; OpenClaw/1.0)"}
        resp = requests.get(source["site_url"], headers=headers, timeout=SCRAPE_TIMEOUT)
        soup = BeautifulSoup(resp.text, "html.parser")

        links = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            text = a.get_text(strip=True)
            if len(text) > 20 and href.startswith("http"):
                links.append({"title": text, "url": href})

        for link in links[:max_articles]:
            if is_pr_article(link["title"], source):
                continue
            articles.append({
                "source_id": source["id"],
                "title": link["title"],
                "url": link["url"],
                "content_raw": "",
                "published_at": datetime.now(timezone.utc).isoformat(),
                "branch": None,
                "duplicate_count": 1,
            })

    except Exception as e:
        FETCH_ERRORS.append(source.get("name", source.get("id", "?")))
        print(f"  Web scrape error for {source['name']}: {e}")

    return articles

# --- Deduplication ---
def deduplicate_batch(articles: list) -> list:
    seen_urls = set()
    unique = []
    for a in articles:
        if a["url"] not in seen_urls:
            seen_urls.add(a["url"])
            unique.append(a)
    return unique

# --- item 5 (2026-06-22): three fetch tiers (full / normal / light), config-driven ---
def resolve_fetch_caps(config):
    """Pick the per-source cap for the active fetch profile. Three tiers in config['fetch_profiles']
    (full / normal / light, default {50,30,10}); a missing/unknown profile falls back to 'normal'.
    Returns (profile, max_per_source, safety_ceiling). Pure + tolerant of a hollow/broken config."""
    def _cfg(key, default):
        try:
            v = config.get(key, default)
            return default if v is None else v
        except Exception:
            return default
    profiles = _cfg("fetch_profiles", {"full": 50, "normal": 30, "light": 10})
    if not isinstance(profiles, dict) or not profiles:
        profiles = {"full": 50, "normal": 30, "light": 10}
    profile = str(_cfg("fetch_profile", "normal")).strip().lower()
    if profile not in profiles:
        profile = "normal" if "normal" in profiles else next(iter(profiles))
    try:
        cap = int(profiles.get(profile, 30))
    except (TypeError, ValueError):
        cap = 30
    return (profile, cap, int(_cfg("fetch_safety_ceiling", 3000)))


# --- Main Fetcher ---
def run_fetcher():
    config = load_config()
    sb = get_supabase()
    start_time = time.time()

    print("OpenClaw Fetcher starting...")
    FETCH_ERRORS.clear()

    existing = sb.table("raw_articles").select("id").limit(1).execute()
    is_first_run = len(existing.data) == 0
    today_jst = datetime.now(JST).strftime("%a").lower()[:3]  # mon..sun, §8.7 weekday gate

    print(f"  Mode: {'first run' if is_first_run else 'regular'} | JST day: {today_jst} | per-source windows (§8.1)")

    sources_result = sb.table("sources").select("*").eq("active", True).execute()
    sources = sources_result.data
    junk_patterns = load_junk_patterns(sb)
    print(f"  Loaded {len(junk_patterns)} junk patterns")

    priority_types = config.get("priority_source_types", ["vc_blog", "research", "blog"])
    fetch_profile, max_per_source, safety_ceiling = resolve_fetch_caps(config)
    print(f"  Fetch profile: {fetch_profile} (max/source={max_per_source}, safety ceiling={safety_ceiling})")

    priority_sources = [s for s in sources if s.get("source_type") in priority_types]
    news_sources = [s for s in sources if s.get("source_type") not in priority_types]

    all_articles = []

    print(f"\nFetching priority sources ({len(priority_sources)})...")
    for source in priority_sources:
        articles, note = fetch_one(config, source, is_first_run, today_jst, max_per_source)
        print(f"  {source['name']}... {note}")
        if articles:
            all_articles.extend(articles)

    print(f"\nFetching news sources ({len(news_sources)})...")
    for source in news_sources:
        weight = source.get("weight", 1.0)
        source_limit = max(1, int(max_per_source * weight))

        articles, note = fetch_one(config, source, is_first_run, today_jst, source_limit)
        print(f"  {source['name']} (weight={weight}, limit={source_limit})... {note}")
        if articles:
            all_articles.extend(articles)

    # Article cap: NO order-based truncation under normal load — every active source is fetched in
    # full (each to its own per-source limit). Only a high SAFETY CEILING guards a runaway bug; if
    # exceeded, cut RANDOMLY across ALL fetched articles (never by source order), so no source — or a
    # story that's just concluding — is systematically starved.
    fetched_total = len(all_articles)
    if fetched_total > safety_ceiling:
        all_articles = random.sample(all_articles, safety_ceiling)
        print(f"\n  SAFETY CEILING hit: {fetched_total} > {safety_ceiling}; randomly sampled down to "
              f"{safety_ceiling} (this is abnormal — likely a runaway bug; investigate).")
    else:
        print(f"\n  Fetched {fetched_total} articles (safety ceiling {safety_ceiling}; no truncation).")

    all_articles = deduplicate_batch(all_articles)
    print(f"\nAfter deduplication: {len(all_articles)} articles")

    saved = 0
    skipped_junk = 0
    skipped_dup = 0
    insert_errors = 0

    for article in all_articles:
        if is_junk_url(article["url"], article["title"], junk_patterns):
            skipped_junk += 1
            continue
        if is_duplicate(sb, article["url"], article["title"]):
            skipped_dup += 1
            continue
        try:
            sb.table("raw_articles").insert(article).execute()
            saved += 1
        except Exception as e:
            insert_errors += 1
            print(f"  Insert error: {e}")

    duration_ms = int((time.time() - start_time) * 1000)

    # Honest status: do NOT hard-code "success". Feed errors (swallowed per source)
    # and insert errors both mean we fetched less than intended.
    feed_errors = len(FETCH_ERRORS)
    status = "success" if (feed_errors == 0 and insert_errors == 0) else "partial"
    error = None
    if status == "partial":
        error = f"{feed_errors} source(s) failed to fetch, {insert_errors} insert error(s)"
        print(f"  ALERT: fetcher degraded — {error}"
              + (f"; sources: {', '.join(FETCH_ERRORS[:10])}" if FETCH_ERRORS else ""))

    record_run(sb, {
        "agent_name": "fetcher",
        "model_used": "none",
        "tokens_in": 0,
        "tokens_out": 0,
        "cost_usd": 0.0,
        "duration_ms": duration_ms,
        "status": status,
        "error": error,
    })

    print(f"\nFetcher done.")
    print(f"  Saved: {saved}")
    print(f"  Skipped (junk): {skipped_junk}")
    print(f"  Skipped (duplicate): {skipped_dup}")
    print(f"  Time: {duration_ms}ms")
    return saved

if __name__ == "__main__":
    run_fetcher()