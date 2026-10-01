"""
Tests for manage.py's pure helpers: the sources/interests file validation, the add-or-update plan,
and that the shipped sources template matches the SQL starter seed.

    venv\\Scripts\\python.exe tests\\test_manage.py
"""
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
import manage  # noqa: E402

PASS = []


def ok(name, cond):
    if not cond:
        raise AssertionError(name)
    PASS.append(name)


def raises(fn):
    try:
        fn()
    except ValueError:
        return True
    return False


def test_template_parses_and_matches_sql_seed():
    doc = manage.load_yaml(os.path.join(ROOT, "config", "sources.example.yaml"))
    rows = manage.source_rows(doc)
    ok("template_has_sources", len(rows) >= 20)
    sql = open(os.path.join(ROOT, "sql", "seed_sources.sql"), encoding="utf-8").read()
    sql_names = set(re.findall(r"^\s*\('((?:[^']|'')+)',", sql, flags=re.M))
    ok("same_names_as_sql_seed", {r["name"] for r in rows} == sql_names)


def test_bad_source_rows_rejected():
    ok("missing_category", raises(lambda: manage.source_rows({"sources": [{"name": "A"}]})))
    ok("unknown_field", raises(lambda: manage.source_rows({"sources": [{"name": "A", "category": "x", "rss_url": "u", "colour": "red"}]})))
    ok("duplicate_name", raises(lambda: manage.source_rows({"sources": [
        {"name": "A", "category": "x", "rss_url": "u"}, {"name": "A", "category": "y", "rss_url": "u"}]})))
    ok("rss_without_url", raises(lambda: manage.source_rows({"sources": [{"name": "A", "category": "x"}]})))
    ok("scrape_without_url_ok", not raises(lambda: manage.source_rows({"sources": [
        {"name": "A", "category": "x", "has_rss": False, "fetch_mode": "browser_required", "site_url": "s"}]})))


def test_context_rows():
    doc = manage.load_yaml(os.path.join(ROOT, "config", "interests.example.yaml"))
    rows = manage.context_rows(doc)
    kinds = [r["kind"] for r in rows]
    ok("interests_and_hypotheses", "interest" in kinds and "hypothesis" in kinds)
    ok("weights_int", all(isinstance(r["weight"], int) for r in rows if r["kind"] == "interest"))
    ok("missing_topic_rejected", raises(lambda: manage.context_rows({"interests": [{"weight": 1}]})))
    ok("duplicate_topic_rejected", raises(lambda: manage.context_rows({"interests": [{"topic": "x"}, {"topic": "x"}]})))
    ok("same_topic_both_kinds_ok", not raises(lambda: manage.context_rows({"interests": [{"topic": "x"}], "hypotheses": [{"topic": "x"}]})))
    ins, upd = manage.plan_upsert([{"kind": "hypothesis", "topic": "x"}], {("interest", "x"): "id-i"}, ("kind", "topic"))
    ok("kind_topic_key", len(ins) == 1 and not upd)


def test_plan_upsert_adds_and_updates_never_deletes():
    rows = [{"name": "A", "weight": 1}, {"name": "B", "weight": 2}]
    ins, upd = manage.plan_upsert(rows, {"B": "id-b", "C": "id-c"}, "name")
    ok("insert_new", [r["name"] for r in ins] == ["A"])
    ok("update_existing", upd == [("id-b", {"name": "B", "weight": 2})])
    ok("untouched_not_deleted", all(r["name"] != "C" for r in ins) and all(i != "id-c" for i, _ in upd))


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
            except Exception as e:
                fails += 1
                print(f"FAIL {name}: {type(e).__name__}: {e}")
    print(f"{len(PASS)} checks passed, {fails} test(s) failed")
    sys.exit(1 if fails else 0)
