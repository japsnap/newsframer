"""
Run every tests/test_*.py and print one aggregate pass/fail summary. Each test file
is a self-contained script that exits non-zero on failure, so this just shells each
and checks the exit code — no framework, matching the repo's test idiom.

    venv\\Scripts\\python.exe tests\\run_all.py
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable


def main():
    files = sorted(f for f in os.listdir(HERE) if f.startswith("test_") and f.endswith(".py"))
    failed = []
    for f in files:
        # utf-8 + replace: test files print 🔍 / ⚠ / Urdu glyphs that crash the default
        # cp1252 reader on Windows.
        r = subprocess.run([PY, os.path.join(HERE, f)], capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        out = (r.stdout or "").strip().splitlines()
        last = out[-1] if out else "(no output)"
        status = "ok  " if r.returncode == 0 else "FAIL"
        if r.returncode != 0:
            failed.append(f)
            if r.stderr.strip():
                last = (last + " | " + r.stderr.strip().splitlines()[-1])[:160]
        print(f"  [{status}] {f:<32} {last}")
    print()
    if failed:
        print(f"SUITE FAILED: {len(failed)}/{len(files)} file(s): {', '.join(failed)}")
        return 1
    print(f"SUITE OK: all {len(files)} test files passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
