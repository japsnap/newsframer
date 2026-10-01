"""
Tests for the open-source defaults: the brief file output, the subscription switch and its
fallback notice, and the named operator timezone. Real artifacts are read back from a temp dir.

    venv\\Scripts\\python.exe tests\\test_public_defaults.py
"""
import os
os.environ.setdefault("NEWSFRAMER_NO_ALERTS", "1")  # tests never send real alerts
import sys
import tempfile
from datetime import datetime, timezone

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "agents"))
import deliver_brief as db  # noqa: E402
import cc_writer  # noqa: E402
from operator_tz import operator_tz  # noqa: E402

PASS = []


def ok(name, cond):
    if not cond:
        raise AssertionError(name)
    PASS.append(name)


def test_brief_file_written_and_read_back():
    with tempfile.TemporaryDirectory() as d:
        before = os.listdir(d)
        p = db.write_brief_file({"date": "2026-01-02", "content_en": "## Theme\nBody text"}, out_dir=d)
        ok("file_absent_before", before == [])
        ok("file_name", os.path.basename(p) == "brief-2026-01-02.md")
        with open(p, encoding="utf-8") as f:
            ok("file_content", f.read() == "## Theme\nBody text")


def test_use_subscription_precedence():
    ok("global_on", cc_writer.use_subscription({"use_subscription": True}, "classifier"))
    ok("stage_off_wins", not cc_writer.use_subscription({"use_subscription": True, "classifier_use_subscription": False}, "classifier"))
    ok("stage_on_wins", cc_writer.use_subscription({"use_subscription": False, "writer_use_subscription": True}, "writer"))
    ok("default_off", not cc_writer.use_subscription({}, "writer"))


def test_fallback_is_logged_and_api_answers():
    calls = {}

    def fake_sub(*a, **k):
        raise RuntimeError("quota exhausted")

    def fake_api(model=None, messages=None, **kw):
        calls["model"] = model
        return "api-response"

    real_sub, real_base = cc_writer.complete_via_subscription, cc_writer.BASE_DIR
    with tempfile.TemporaryDirectory() as d:
        cc_writer.complete_via_subscription, cc_writer.BASE_DIR = fake_sub, d
        cc_writer._NOTIFIED.discard("unit")
        try:
            fn = cc_writer.completion_fn({"use_subscription": True, "notify_on_subscription_fallback": False},
                                         "unit", api_completion=fake_api)
            out = fn(model="gemini/x", messages=[{"role": "user", "content": "hi"}])
            ok("api_answered", out == "api-response" and calls["model"] == "gemini/x")
            log = os.path.join(d, "logs", "subscription-fallback.log")
            ok("log_written", os.path.exists(log))
            with open(log, encoding="utf-8") as f:
                ok("log_names_stage", "\tunit\t" in f.read())
        finally:
            cc_writer.complete_via_subscription, cc_writer.BASE_DIR = real_sub, real_base


def test_operator_timezone():
    tok = operator_tz({"operator_timezone": "Asia/Tokyo"})
    ok("tokyo_plus9", datetime(2026, 1, 1, tzinfo=timezone.utc).astimezone(tok).utcoffset().total_seconds() == 9 * 3600)
    lon = operator_tz({"operator_timezone": "Europe/London"})
    ok("london_dst", datetime(2026, 7, 1, tzinfo=timezone.utc).astimezone(lon).utcoffset().total_seconds() == 3600)
    ok("offset_fallback", operator_tz({"operator_timezone": "Not/AZone", "operator_tz_offset_hours": 5}).utcoffset(None).total_seconds() == 5 * 3600)


def test_brief_payload_lists_cited_articles_with_sources():
    brief = {"id": "b1", "date": "2026-01-02", "content_en": "## T", "article_ids": ["a1", "a2", "gone"]}
    arts = [{"id": "a1", "title": "One", "url": "u1", "source_id": "s1", "published_at": "p"},
            {"id": "a2", "title": "Two", "url": "u2", "source_id": None}]
    p = db.brief_payload(brief, arts, {"s1": {"name": "Wire", "category": "tech"}})
    ok("payload_markdown", p["markdown"] == "## T" and p["date"] == "2026-01-02")
    ok("payload_articles", [a["id"] for a in p["articles"]] == ["a1", "a2"])
    ok("payload_source", p["articles"][0]["source"] == "Wire" and p["articles"][1]["source"] is None)


def test_post_command_runs_with_paths():
    with tempfile.TemporaryDirectory() as d:
        md = os.path.join(d, "brief-x.md")
        js = os.path.join(d, "brief-x.json")
        marker = os.path.join(d, "ran.txt")
        open(md, "w").close()
        script = os.path.join(d, "publish.py")
        with open(script, "w", encoding="utf-8") as f:
            f.write("import sys\nopen(sys.argv[3], 'w', encoding='utf-8').write(sys.argv[1] + '|' + sys.argv[2])\n")
        cmd = f'"{sys.executable}" "{script}" {{md}} {{json}} "{marker}"'
        ok("marker_absent_before", not os.path.exists(marker))
        rc = db.run_post_command(md, js, command=cmd, timeout=60)
        ok("post_rc_0", rc == 0)
        with open(marker, encoding="utf-8") as f:
            ok("post_got_paths", f.read() == md + "|" + js)
        ok("no_command_noop", db.run_post_command(md, js, command="") is None)


def test_wizard_copies_templates_and_never_overwrites():
    import setup_wizard as sw
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "config"))
        for n in ("models", "sources", "interests"):
            with open(os.path.join(d, "config", f"{n}.example.yaml"), "w", encoding="utf-8") as f:
                f.write(f"template: {n}\n")
        with open(os.path.join(d, "config", "models.yaml"), "w", encoding="utf-8") as f:
            f.write("mine: true\n")
        made = sw.ensure_settings_file(d, print_fn=lambda s: None)
        ok("copied_missing_two", sorted(os.path.basename(m) for m in made) == ["interests.yaml", "sources.yaml"])
        with open(os.path.join(d, "config", "models.yaml"), encoding="utf-8") as f:
            ok("existing_untouched", f.read() == "mine: true\n")
        with open(os.path.join(d, "config", "sources.yaml"), encoding="utf-8") as f:
            ok("copy_content", f.read() == "template: sources\n")


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
