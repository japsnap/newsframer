"""
NewsFramer brief builder — runs the 5 engines (NO Dispatcher) to produce today's
brief into Supabase. Delivery is OpenClaw's job, not this script's.

This is run_pipeline.py minus the dispatcher step. It WRAPS the existing engines
and invokes them unchanged; it does not import or reimplement any engine logic.
Invoked by the OpenClaw `newsframer-deliver-brief` skill via the project venv.
"""
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).parent
PYTHON = sys.executable

sys.path.insert(0, str(BASE_DIR / "agents"))
import gen_lock  # noqa: E402  (single-generation lock — double-generation fix)

# Fetch -> Classify -> Dedup(apply) -> Analyze -> Write.
# NO dispatcher on purpose: OpenClaw delivers the finished brief.
AGENTS = [
    ("fetcher",      [PYTHON, str(BASE_DIR / "agents" / "fetcher.py")]),
    ("classifier",   [PYTHON, str(BASE_DIR / "agents" / "classifier.py")]),
    ("deduplicator", [PYTHON, str(BASE_DIR / "agents" / "deduplicator.py"), "--apply"]),
    ("analyst",      [PYTHON, str(BASE_DIR / "agents" / "analyst.py")]),
    ("writer",       [PYTHON, str(BASE_DIR / "agents" / "writer.py")]),
]


def _cfg_flag(key, default=False):
    try:
        import yaml
        with open(BASE_DIR / "config" / "models.yaml", encoding="utf-8") as f:
            return bool((yaml.safe_load(f) or {}).get(key, default))
    except Exception:
        return default


def _cfg_get(key, default):
    try:
        import yaml
        with open(BASE_DIR / "config" / "models.yaml", encoding="utf-8") as f:
            v = (yaml.safe_load(f) or {}).get(key, default)
            return default if v is None else v
    except Exception:
        return default


# NF-NEW10: collapse same-story wire copies BEFORE the analyst — only when enabled in
# config (default off => pipeline byte-for-byte unchanged). Runs after the deduplicator
# (which sets the cluster_id it reuses) and before the analyst (which then skips the
# soft-deleted copies).
if _cfg_flag("title_dedup_enabled"):
    _ai = next(i for i, (n, _) in enumerate(AGENTS) if n == "analyst")
    AGENTS.insert(_ai, ("title_dedup", [PYTHON, str(BASE_DIR / "agents" / "title_dedup.py"), "--apply"]))


def run_agent(name, cmd):
    print(f"\n[{datetime.utcnow().isoformat()}] Starting {name}...")
    start = time.time()
    result = subprocess.run(cmd, cwd=BASE_DIR)
    elapsed = round(time.time() - start, 1)
    if result.returncode == 0:
        print(f"[{datetime.utcnow().isoformat()}] {name} done ({elapsed}s)")
        return True
    print(f"[{datetime.utcnow().isoformat()}] {name} FAILED (exit {result.returncode}, {elapsed}s)")
    return False


def main():
    # SINGLE-GENERATION LOCK (double-generation fix): only one build runs per slot+JST-day. When the
    # cron command times out mid-build and OpenClaw re-invokes the job, this second run finds the live
    # lock and NO-OPS (exit 0) instead of re-running the whole pipeline (the analyst is the cost).
    lock_enabled = bool(_cfg_get("run_lock_enabled", True))
    locks_dir = str(BASE_DIR / ".runstate")
    lock_name = "run_brief"
    lock_key = None
    have_lock = False
    if lock_enabled:
        tz = int(_cfg_get("operator_tz_offset_hours", 9))
        jst_date = (datetime.utcnow() + timedelta(hours=tz)).date().isoformat()
        lock_key = f"brief-{jst_date}"
        stale_s = int(_cfg_get("run_lock_stale_minutes", 60)) * 60
        have_lock, holder = gen_lock.acquire(lock_name, lock_key, locks_dir, stale_s)
        if not have_lock:
            age = int(time.time() - float(holder.get("ts", 0)))
            print(f"run_brief: SKIP — a generation for {lock_key} is already running "
                  f"(pid={holder.get('pid')}, age={age}s). No-op (single-generation lock).")
            sys.exit(0)

    rc = 0
    try:
        # NF-14: one trace_id ties this run's engine rows together in execution_log. Each engine is a
        # subprocess and inherits it via the environment; run_log mirrors it best-effort (never blocking).
        trace_id = uuid.uuid4().hex
        os.environ["NEWSFRAMER_TRACE_ID"] = trace_id
        os.environ.setdefault("NEWSFRAMER_TASK_TYPE", "brief")
        print(f"=== NewsFramer brief build start {datetime.utcnow().isoformat()} (no dispatcher) | trace={trace_id} ===")
        any_failed = False
        for name, cmd in AGENTS:
            if not run_agent(name, cmd):
                any_failed = True
                # Continue — downstream engines may still have prior data to work with.
        print(f"\n=== Brief build complete. Status: {'PARTIAL FAILURE' if any_failed else 'OK'} ===")
        rc = 1 if any_failed else 0
    finally:
        if have_lock:
            gen_lock.release(lock_name, lock_key, locks_dir)
    sys.exit(rc)


if __name__ == "__main__":
    main()
