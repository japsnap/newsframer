"""
Best-effort writer for the agent_runs health log (shared by all agents), plus a best-effort
mirror into execution_log (NF-14 / spec §9) for per-run observability + cost trace.

The agent_runs insert is the LAST thing an agent does, after every real side effect (articles
classified, scores written, briefing saved). If that insert raised, the agent would exit
non-zero and the orchestrator (run_brief.py -> OpenClaw) could treat a *successfully built*
brief as a failed run and withhold delivery. Bookkeeping must never sink the brief: record_run
logs and swallows. The execution_log mirror is likewise FULLY ISOLATED — a missing table, a
disabled flag, or a failed insert can never affect agent_runs or the brief.
"""
import os

# execution_log-only fields that ride through the payload (build_exec_row maps them). agent_runs
# has NO such columns — passing them through made the writer's agent_runs insert fail silently on
# every run from 2026-06-18 to 2026-07-22 (the best-effort swallow hid it). Strip before insert.
EXEC_ONLY_FIELDS = ("artifact_verified", "linked_hypotheses")


def record_run(sb, payload):
    """Insert one agent_runs row, best-effort. Returns True on success, False if the agent_runs
    insert failed (logged, never raised). Also mirrors the row into execution_log (best-effort,
    isolated) so every engine of one run shares a trace_id."""
    ok = True
    try:
        ar_payload = {k: v for k, v in payload.items() if k not in EXEC_ONLY_FIELDS}
        sb.table("agent_runs").insert(ar_payload).execute()
    except Exception as e:
        print(f"  WARN: agent_runs insert failed (non-fatal bookkeeping): {e}")
        ok = False
    try:
        mirror_execution_log(sb, payload)
    except Exception as e:
        print(f"  (execution_log mirror skipped: {type(e).__name__})")
    return ok


def build_exec_row(payload, trace_id, task_type, project="newsframer"):
    """Map an agent_runs payload -> an execution_log row (NF-14). Pure. `trace_id` ties one
    pipeline run's engines together; task_type/project label the run. Engine-specific fields
    (linked_hypotheses, artifact_verified) ride through the payload when an engine sets them."""
    return {
        "trace_id": trace_id,
        "project": project,
        "task_type": task_type,
        "agent": payload.get("agent_name"),
        "model_used": payload.get("model_used"),
        "actual_cost": payload.get("cost_usd") or 0,
        "tokens_in": payload.get("tokens_in") or 0,
        "tokens_out": payload.get("tokens_out") or 0,
        "status": payload.get("status"),
        "error_trace": payload.get("error"),
        "linked_hypotheses": payload.get("linked_hypotheses"),
        "artifact_verified": bool(payload.get("artifact_verified", False)),
    }


def mirror_execution_log(sb, payload, trace_id=None, task_type=None, enabled=None):
    """Best-effort execution_log mirror (NF-14). Gated by exec_log_enabled (default on). The run's
    trace_id comes from NEWSFRAMER_TRACE_ID (set by run_brief); a standalone engine run gets a
    'solo-<agent>' trace. Returns True if a row was inserted. The caller wraps this; it must never
    raise into the brief."""
    if enabled is None:
        enabled = _exec_log_enabled()
    if not enabled:
        return False
    trace_id = trace_id or os.environ.get("NEWSFRAMER_TRACE_ID") or f"solo-{payload.get('agent_name', '?')}"
    task_type = task_type or os.environ.get("NEWSFRAMER_TASK_TYPE", "brief")
    sb.table("execution_log").insert(build_exec_row(payload, trace_id, task_type, _project_name())).execute()
    return True


def _project_name():
    """Read project_name from config/models.yaml (default 'newsframer'). Wrapped — a missing/broken
    config never breaks logging."""
    try:
        import yaml
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(base, "config", "models.yaml"), encoding="utf-8") as f:
            return str((yaml.safe_load(f) or {}).get("project_name", "newsframer"))
    except Exception:
        return "newsframer"


def _exec_log_enabled():
    """Read exec_log_enabled from config/models.yaml (default True). Wrapped — a missing/broken
    config never breaks logging."""
    try:
        import yaml
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(base, "config", "models.yaml"), encoding="utf-8") as f:
            return bool((yaml.safe_load(f) or {}).get("exec_log_enabled", True))
    except Exception:
        return True
