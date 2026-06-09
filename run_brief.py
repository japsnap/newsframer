"""
NewsFramer brief builder — runs the 5 engines (NO Dispatcher) to produce today's
brief into Supabase. Delivery is OpenClaw's job, not this script's.

This is run_pipeline.py minus the dispatcher step. It WRAPS the existing engines
and invokes them unchanged; it does not import or reimplement any engine logic.
Invoked by the OpenClaw `newsframer-deliver-brief` skill via the project venv.
"""
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent
PYTHON = sys.executable

# Fetch -> Classify -> Dedup(apply) -> Analyze -> Write.
# NO dispatcher on purpose: OpenClaw delivers the finished brief.
AGENTS = [
    ("fetcher",      [PYTHON, str(BASE_DIR / "agents" / "fetcher.py")]),
    ("classifier",   [PYTHON, str(BASE_DIR / "agents" / "classifier.py")]),
    ("deduplicator", [PYTHON, str(BASE_DIR / "agents" / "deduplicator.py"), "--apply"]),
    ("analyst",      [PYTHON, str(BASE_DIR / "agents" / "analyst.py")]),
    ("writer",       [PYTHON, str(BASE_DIR / "agents" / "writer.py")]),
]


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
    print(f"=== NewsFramer brief build start {datetime.utcnow().isoformat()} (no dispatcher) ===")
    any_failed = False
    for name, cmd in AGENTS:
        if not run_agent(name, cmd):
            any_failed = True
            # Continue — downstream engines may still have prior data to work with.
    print(f"\n=== Brief build complete. Status: {'PARTIAL FAILURE' if any_failed else 'OK'} ===")
    sys.exit(1 if any_failed else 0)


if __name__ == "__main__":
    main()
