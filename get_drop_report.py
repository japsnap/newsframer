"""
get_drop_report.py — return the full ("more") write-up for a drop-report.

The OpenClaw `newsframer` agent calls this when you reply "more: <slug>" to a
drop-report in the Telegram brief. It reads the local JSON store the Writer
writes (data/drop_reports/<date>.json) — no DB, no LLM (the long form was
generated and stored when the brief was built).

Usage:
  python get_drop_report.py <slug>                 # search today, then recent days
  python get_drop_report.py "more: <slug>"         # the leading 'more:' is tolerated
  python get_drop_report.py <slug> --date 2026-06-11
  python get_drop_report.py --list                 # list today's drop slugs
"""
import os
import sys
import json
import glob
import argparse

import yaml

try:  # titles/summaries can contain non-latin glyphs; don't crash the console.
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

BASE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(BASE, "data", "drop_reports")


def _load_config():
    with open(os.path.join(BASE, "config", "models.yaml"), "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


try:  # wrapped so a missing/broken config can't break this CLI helper
    _CFG = _load_config() or {}
except Exception:
    _CFG = {}

REPLY_TRIGGER = str(_CFG.get("drop_report_reply_trigger", "more:"))


def _store_files(date=None, days_back=10):
    if date:
        return [os.path.join(STORE, f"{date}.json")]
    return sorted(glob.glob(os.path.join(STORE, "*.json")), reverse=True)[:days_back]


def _read(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def normalize_slug(s):
    s = (s or "").strip().lower()
    _trig = REPLY_TRIGGER.lower()
    if _trig and s.startswith(_trig):
        s = s[len(_trig):].strip()
    return s


def find(slug, date=None, days_back=10):
    slug = normalize_slug(slug)
    for path in _store_files(date, days_back):
        data = _read(path)
        if not data:
            continue
        drops = data.get("drops", [])
        # exact slug first, then prefix/contains as a convenience.
        for d in drops:
            if d.get("slug", "").lower() == slug:
                return d, data.get("date")
        for d in drops:
            if slug and slug in d.get("slug", "").lower():
                return d, data.get("date")
    return None, None


def list_today(date=None, days_back=10):
    out = []
    for path in _store_files(date, days_back):
        data = _read(path)
        if not data:
            continue
        for d in data.get("drops", []):
            out.append((data.get("date"), d.get("slug"), d.get("title")))
        if out:
            break  # only the most recent non-empty day
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slug", nargs="?", help="drop slug (the value after 'more:')")
    ap.add_argument("--date", help="YYYY-MM-DD; defaults to most recent days")
    ap.add_argument("--list", action="store_true", help="list available drop slugs")
    args = ap.parse_args()

    if args.list or not args.slug:
        items = list_today(args.date)
        if not items:
            print("No drop-reports found.")
            return 1
        print("Available drop-reports:")
        for date, slug, title in items:
            print(f"  [{date}] more: {slug}  —  {title}")
        return 0

    d, date = find(args.slug, args.date)
    if not d:
        print(f'No drop-report matching "{normalize_slug(args.slug)}".')
        items = list_today(args.date)
        if items:
            print("Did you mean:")
            for dt, slug, title in items:
                print(f"  more: {slug}  —  {title}")
        return 1

    print(f"🔍 {d.get('title','')}  ({d.get('source','')})  [{date}]")
    print(d.get("url", ""))
    print()
    print(d.get("long") or d.get("short") or "(no summary stored)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
