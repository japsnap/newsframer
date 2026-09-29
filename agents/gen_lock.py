"""
Per-slot single-generation lock (double-generation fix).

Only one pipeline build may run per scheduled slot+day. A concurrent or cron-retry invocation that
finds a LIVE lock for the same key NO-OPS instead of re-running the whole pipeline (the analyst is
the cost). Local-file based — the pipeline runs on one always-on PC, so no DB/schema change is
needed. A lock older than stale_seconds is treated as a crashed run and reclaimed, so a dead run can
never deadlock a later one. Filesystem-only + injectable now/pid => unit-testable.
"""
import json
import os
import time


def _path(locks_dir, name):
    return os.path.join(locks_dir, f"{name}.lock")


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def acquire(name, key, locks_dir, stale_seconds, now=None, pid=None):
    """Try to acquire (name, key). Returns (acquired, holder).

    - acquired True  + holder = our record  => we hold the lock; caller MUST release() in a finally.
    - acquired False + holder = their record => a LIVE run holds it for the same key; caller no-ops.

    A lock with a DIFFERENT key (a new day/slot) or one older than stale_seconds is reclaimed, so a
    crashed run can never deadlock the next one."""
    now = time.time() if now is None else now
    pid = os.getpid() if pid is None else pid
    os.makedirs(locks_dir, exist_ok=True)
    path = _path(locks_dir, name)
    holder = _read(path)
    if holder and holder.get("key") == key and (now - float(holder.get("ts", 0))) < stale_seconds:
        return False, holder
    rec = {"key": key, "pid": pid, "ts": now}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rec, f)
    return True, rec


def release(name, key, locks_dir):
    """Release the lock iff we still hold it for `key` (never delete a newer run's lock)."""
    path = _path(locks_dir, name)
    holder = _read(path)
    if holder and holder.get("key") == key:
        try:
            os.remove(path)
        except OSError:
            pass
