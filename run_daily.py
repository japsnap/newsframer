"""
NewsFramer daily Telegram job — BUILD then DELIVER in ONE process.

Why this exists (no-delivery incident, 2026-06-14): the cron used to run the build
(run_brief.py) and the delivery (deliver_brief.py) as TWO separate agent exec steps.
On a slow build day the deliver step fired BEFORE the writer had committed today's
brief, so deliver_brief found "no fresh brief" and sent nothing. Folding both into a
single process guarantees deliver runs only AFTER the build has finished — and because
it is one child process, the delivery still completes even if the calling OpenClaw
agent stops watching the exec.

The §4.3 confirmed-send gating is untouched: deliver_brief.py still records a brief's
article IDs ONLY after every chunk returns a real messageId, and alerts on failure.

Usage:
  python run_daily.py            # build today's brief, then deliver to Telegram
  python run_daily.py --dry-run  # SKIP the build; just show deliver_brief's chunk
                                 #   plan (no send, no recording, no rebuild)

Exit: the delivery step's exit code (0 = sent+recorded or nothing fresh to send;
1 = send failed and alerted; 2 = no fresh brief). Build status is printed, not fatal:
run_brief may report PARTIAL yet still have written a good brief — deliver_brief's
freshness/non-empty gate is the real decider.
"""
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
PY = sys.executable

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def _step(name, cmd):
    print(f"\n=== {name}: {' '.join(str(c) for c in cmd)} ===", flush=True)
    t0 = time.time()
    rc = subprocess.run(cmd, cwd=str(BASE)).returncode
    print(f"=== {name} exit={rc} ({round(time.time() - t0, 1)}s) ===", flush=True)
    return rc


def main():
    dry = "--dry-run" in sys.argv[1:]

    if dry:
        # Safe smoke: do NOT rebuild (that would create another briefing + re-trigger
        # the §4.3 set-difference). Just exercise the deliver wiring in dry-run.
        deliver_rc = _step("DELIVER (dry-run) deliver_brief.py",
                            [PY, str(BASE / "deliver_brief.py"), "--dry-run"])
        print(f"\nrun_daily: DRY-RUN | DELIVER exit={deliver_rc} (build skipped)", flush=True)
        return deliver_rc

    # STEP 1 — build today's brief into Supabase (blocking; typically ~5-9 min).
    build_rc = _step("BUILD run_brief.py", [PY, str(BASE / "run_brief.py")])
    # STEP 2 — deliver to Telegram + record §4.3 ONLY on a confirmed send. Runs
    # regardless of build_rc: a PARTIAL build (exit 1) can still have written a good
    # brief; deliver_brief decides on the actual artifact, not on the build's exit code.
    deliver_rc = _step("DELIVER deliver_brief.py", [PY, str(BASE / "deliver_brief.py")])

    print(f"\nrun_daily: BUILD exit={build_rc} | DELIVER exit={deliver_rc}", flush=True)
    return deliver_rc


if __name__ == "__main__":
    sys.exit(main())
