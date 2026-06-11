"""
Tests for check_run_health.py — the pure detection logic of the missed-run /
partial alert (spec §4.5). No DB, no Telegram.

    venv\\Scripts\\python.exe tests\\test_check_run_health.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import check_run_health as h  # noqa: E402

PASS = []


def ok(name, cond):
    if not cond:
        raise AssertionError(name)
    PASS.append(name)


def run(agent_name, status, error=None):
    return {"agent_name": agent_name, "status": status, "error": error}


HEALTHY_RUNS = [
    run("fetcher", "success"), run("classifier", "success"),
    run("deduplicator", "success"), run("analyst", "success"), run("writer", "success"),
]
BRIEF = {"id": "b1", "date": "2026-06-11"}
DELIV = [{"article_id": "a1", "brief_id": "b1"}]


def sev_set(issues):
    return {(i["sev"], i["stage"]) for i in issues}


# --- evaluate_health -------------------------------------------------------
def test_healthy_no_issues():
    ok("healthy", h.evaluate_health(HEALTHY_RUNS, BRIEF, DELIV) == [])


def test_partial_agent_named():
    runs = [run("fetcher", "success"), run("classifier", "partial", "1 batch(es) failed"),
            run("deduplicator", "success"), run("analyst", "success"), run("writer", "success")]
    issues = h.evaluate_health(runs, BRIEF, DELIV)
    ok("partial_one_issue", len(issues) == 1)
    ok("partial_names_classifier", issues[0]["stage"] == "classifier" and issues[0]["sev"] == "alert")
    ok("partial_includes_error", "1 batch" in issues[0]["detail"])


def test_error_agent_named():
    runs = [run("fetcher", "success"), run("analyst", "error", "db down")]
    issues = h.evaluate_health(runs, BRIEF, DELIV)
    ok("error_alert", ("alert", "analyst") in sev_set(issues))


def test_didnt_run_when_no_engine_rows():
    issues = h.evaluate_health([], None, [])
    ok("norun_single", len(issues) == 1 and issues[0]["stage"] == "pipeline" and issues[0]["sev"] == "alert")


def test_no_brief_is_alert():
    issues = h.evaluate_health(HEALTHY_RUNS, None, [])
    ok("nobrief_alert", ("alert", "writer") in sev_set(issues))


def test_quiet_day_is_info_not_alert():
    runs = HEALTHY_RUNS[:-1] + [run("writer", "quiet_day_no_articles")]
    issues = h.evaluate_health(runs, None, [])
    ok("quiet_info", ("info", "writer") in sev_set(issues))
    ok("quiet_no_alert", not any(i["sev"] == "alert" for i in issues))


def test_built_but_not_delivered():
    issues = h.evaluate_health(HEALTHY_RUNS, BRIEF, [])
    ok("delivery_alert", ("alert", "delivery") in sev_set(issues))


# --- build_alert_text ------------------------------------------------------
def test_alert_text_none_when_healthy():
    ok("text_none", h.build_alert_text([], "06:30 JST") is None)


def test_alert_text_has_siren_and_stage():
    runs = [run("classifier", "partial", "boom")]
    txt = h.build_alert_text(h.evaluate_health(runs, BRIEF, DELIV), "06:30 JST")
    ok("text_siren", txt.startswith("🚨"))
    ok("text_stage", "classifier" in txt)


def test_alert_text_info_only_uses_info_marker():
    issues = [{"sev": "info", "stage": "writer", "detail": "quiet day"}]
    txt = h.build_alert_text(issues, "06:30 JST")
    ok("text_info_marker", txt.startswith("ℹ️"))


def main():
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
            except AssertionError as e:
                print(f"FAIL: {e}")
                failed += 1
            except Exception as e:
                print(f"ERROR in {name}: {type(e).__name__}: {e}")
                failed += 1
    print(f"\n{len(PASS)} checks passed, {failed} test(s) failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
