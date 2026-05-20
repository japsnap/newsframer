import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).parent
import sys
PYTHON = sys.executable

AGENTS = [
("fetcher",      [PYTHON, str(BASE_DIR / "agents/fetcher.py")]),
    ("classifier",   [PYTHON, str(BASE_DIR / "agents/classifier.py")]),
    ("deduplicator", [PYTHON, str(BASE_DIR / "agents/deduplicator.py"), "--apply"]),
    ("analyst",      [PYTHON, str(BASE_DIR / "agents/analyst.py")]),
    ("writer",       [PYTHON, str(BASE_DIR / "agents/writer.py")]),
    ("dispatcher",   [PYTHON, str(BASE_DIR / "agents/dispatcher.py")]),
]

def run_agent(name, cmd):
    print(f"\n[{datetime.utcnow().isoformat()}] Starting {name}...")
    start = time.time()
    result = subprocess.run(cmd, cwd=BASE_DIR)
    elapsed = round(time.time() - start, 1)
    if result.returncode == 0:
        print(f"[{datetime.utcnow().isoformat()}] {name} done ({elapsed}s)")
        return True
    else:
        print(f"[{datetime.utcnow().isoformat()}] {name} FAILED (exit {result.returncode}, {elapsed}s)")
        return False

def main():
    print(f"=== NewsFramer pipeline start {datetime.utcnow().isoformat()} ===")
    any_failed = False

    for name, cmd in AGENTS:
        success = run_agent(name, cmd)
        if not success:
            any_failed = True
            # Continue — downstream agents may have prior data to work with

    print(f"\n=== Pipeline complete. Status: {'PARTIAL FAILURE' if any_failed else 'OK'} ===")
    sys.exit(1 if any_failed else 0)

if __name__ == "__main__":
    main()