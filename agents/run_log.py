"""
Best-effort writer for the agent_runs health log (shared by all agents).

The agent_runs insert is the LAST thing an agent does, after every real side
effect (articles classified, scores written, briefing saved). If that insert
raised, the agent would exit non-zero and the orchestrator (run_brief.py ->
OpenClaw) could treat a *successfully built* brief as a failed run and withhold
delivery. Bookkeeping must never sink the brief: record_run logs and swallows.
"""


def record_run(sb, payload):
    """Insert one agent_runs row, best-effort. Returns True on success, False if
    the insert failed (logged, never raised)."""
    try:
        sb.table("agent_runs").insert(payload).execute()
        return True
    except Exception as e:
        print(f"  WARN: agent_runs insert failed (non-fatal bookkeeping): {e}")
        return False
