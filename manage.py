"""
NewsFramer management commands: set up the database and keep your sources and interests in files.

    python manage.py db-init    # create every table and the starter junk filters (safe to re-run)
    python manage.py sync       # write config/sources.yaml + config/interests.yaml into the database
    python manage.py sources    # list the sources in the database, by topic bundle

db-init needs SUPABASE_DB_URL in .env: the Postgres connection string from Supabase (Connect >
Connection string > URI, with your database password filled in). sync and sources use the normal
SUPABASE_URL + SUPABASE_SERVICE_KEY.

sync only adds and updates: a source is matched by `name`, an interest or hypothesis by its kind
and `topic`. Fields you leave out keep the database defaults.
Nothing is ever deleted; set `active: false` in the file to switch one off. Values are never printed.
"""
import argparse
import os
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

SOURCE_FIELDS = {
    "name", "category", "weight", "source_type", "has_rss", "rss_url", "site_url", "language",
    "fetch_mode", "fetch_window_hours", "region", "groundnews_publication_bias",
    "groundnews_factuality", "scrape_days", "active", "notes", "type",
}


# --- pure helpers (tested) --------------------------------------------------------------------
def load_yaml(path):
    p = Path(path)
    if not p.exists():
        return None
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def source_rows(doc):
    """Validated source rows from a sources.yaml document. Raises ValueError on a bad row."""
    rows, seen = [], set()
    for i, s in enumerate((doc or {}).get("sources") or []):
        if not isinstance(s, dict) or not s.get("name") or not s.get("category"):
            raise ValueError(f"sources[{i}]: every source needs at least `name` and `category`")
        unknown = set(s) - SOURCE_FIELDS
        if unknown:
            raise ValueError(f"sources[{i}] ({s['name']}): unknown field(s) {sorted(unknown)}")
        if s["name"] in seen:
            raise ValueError(f"sources[{i}]: duplicate name {s['name']!r}")
        seen.add(s["name"])
        if s.get("has_rss", True) and s.get("fetch_mode", "rss") == "rss" and not s.get("rss_url"):
            raise ValueError(f"sources[{i}] ({s['name']}): an RSS source needs `rss_url`")
        rows.append({"active": True, **s})
    return rows


def context_rows(doc):
    """user_context rows from an interests.yaml document."""
    doc = doc or {}
    rows, seen = [], set()
    for it in doc.get("interests") or []:
        if not it.get("topic"):
            raise ValueError("every interest needs a `topic`")
        rows.append({"kind": "interest", "topic": it["topic"], "weight": int(it.get("weight", 1)),
                     "active": bool(it.get("active", True)), "status": "active"})
    for h in doc.get("hypotheses") or []:
        if not h.get("topic"):
            raise ValueError("every hypothesis needs a `topic`")
        rows.append({"kind": "hypothesis", "topic": h["topic"], "stance": h.get("stance"),
                     "confidence": h.get("confidence"), "reasoning": h.get("reasoning"),
                     "specificity": h.get("specificity", "specific"),
                     "active": bool(h.get("active", True)), "status": "active"})
    for r in rows:
        k = (r["kind"], r["topic"])
        if k in seen:
            raise ValueError(f"duplicate {r['kind']} topic {r['topic']!r}")
        seen.add(k)
    return rows


def row_key(r, key):
    """The match key of a row: one column name, or a tuple of column names."""
    return tuple(r.get(k) for k in key) if isinstance(key, tuple) else r.get(key)


def plan_upsert(rows, existing, key):
    """Split rows into (inserts, updates) against {key_value: id} of existing rows."""
    inserts, updates = [], []
    for r in rows:
        k = row_key(r, key)
        if k in existing:
            updates.append((existing[k], r))
        else:
            inserts.append(r)
    return inserts, updates


# --- commands ---------------------------------------------------------------------------------
def _client():
    from supabase import create_client
    url, key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_KEY")
    if not url or not key:
        sys.exit("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env (python setup_wizard.py).")
    return create_client(url, key)


def _select_all(sb, table, cols, page=1000):
    out, start = [], 0
    while True:
        batch = sb.table(table).select(cols).range(start, start + page - 1).execute().data or []
        out += batch
        if len(batch) < page:
            return out
        start += page


def _apply(sb, table, rows, key, label):
    cols = ", ".join(key) if isinstance(key, tuple) else key
    existing = {row_key(r, key): r["id"] for r in _select_all(sb, table, f"id, {cols}")}
    inserts, updates = plan_upsert(rows, existing, key)
    for rid, r in updates:
        sb.table(table).update(r).eq("id", rid).execute()
    if inserts:
        sb.table(table).insert(inserts, default_to_null=False).execute()  # omitted fields keep DB defaults
    after = len(_select_all(sb, table, "id"))
    print(f"  {label}: {len(inserts)} added, {len(updates)} updated, {after} rows in {table} now")


def cmd_sync(args):
    sb = _client()
    did = False
    src = load_yaml(BASE_DIR / "config" / "sources.yaml")
    if src is None:
        print("  config/sources.yaml not found: copy config/sources.example.yaml to it first.")
    else:
        _apply(sb, "sources", source_rows(src), "name", "sources")
        did = True
    ctx = load_yaml(BASE_DIR / "config" / "interests.yaml")
    if ctx is None:
        print("  config/interests.yaml not found (optional): copy config/interests.example.yaml to add yours.")
    else:
        _apply(sb, "user_context", context_rows(ctx), ("kind", "topic"), "interests + hypotheses")
        did = True
    return 0 if did else 1


def cmd_sources(args):
    sb = _client()
    rows = sb.table("sources").select("name, category, active, has_rss").order("category").execute().data or []
    by = {}
    for r in rows:
        by.setdefault(r.get("category") or "(none)", []).append(r)
    for cat, rs in by.items():
        on = sum(1 for r in rs if r.get("active"))
        print(f"{cat}: {on} active / {len(rs)}")
        for r in rs:
            print(f"   {'on ' if r.get('active') else 'off'}  {r['name']}")
    return 0


def cmd_db_init(args):
    dsn = os.getenv("SUPABASE_DB_URL")
    if not dsn:
        sys.exit("SUPABASE_DB_URL is not set in .env. In Supabase: Connect > Connection string > URI "
                 "(fill in your database password). Or paste sql/schema.sql into the SQL editor instead.")
    import psycopg
    schema = (BASE_DIR / "sql" / "schema.sql").read_text(encoding="utf-8")
    junk = (BASE_DIR / "sql" / "seed_junk_patterns.sql").read_text(encoding="utf-8")
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(schema)
        print("  schema: every table created or already present")
        n = conn.execute("select count(*) from junk_patterns").fetchone()[0]
        if n == 0:
            conn.execute(junk)
            print(f"  junk filters: {conn.execute('select count(*) from junk_patterns').fetchone()[0]} loaded")
        else:
            print(f"  junk filters: {n} already present, left as they are")
    print("Next: python manage.py sync   (loads your sources and interests)")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="NewsFramer database setup and sync")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("db-init", help="create the tables and starter junk filters").set_defaults(fn=cmd_db_init)
    sub.add_parser("sync", help="write config/sources.yaml + config/interests.yaml into the database").set_defaults(fn=cmd_sync)
    sub.add_parser("sources", help="list sources in the database").set_defaults(fn=cmd_sources)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
