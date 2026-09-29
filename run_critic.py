"""
Run the Critic over the latest brief — READ-ONLY operator inspection.

Loads the most recent briefing from Supabase, runs agents/critic.critique(), and
prints the severity report. Sends NOTHING, records NOTHING, changes NOTHING — a
sanity check in the spirit of eval_classifier.py. The Critic (§10.13 / NF-F1) is
not yet wired into delivery; this lets you eyeball what it would say.

    venv\\Scripts\\python.exe run_critic.py
"""
import os
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv
from supabase import create_client

BASE = Path(__file__).resolve().parent
load_dotenv(BASE / ".env")
sys.path.insert(0, str(BASE / "agents"))
import critic  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

LANG_COL = "content_en"


def _config():
    try:
        with open(BASE / "config" / "models.yaml", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _cap(config, n_themes):
    """The same theme-scaled character cap the Writer uses, so overrun is judged fairly."""
    per = int(config.get("writer_per_theme_chars", 2500))
    floor = int(config.get("writer_max_chars_floor", 6000))
    ceiling = int(config.get("writer_max_chars_ceiling", 16000))
    return max(floor, min(ceiling, per * max(1, n_themes)))


def main():
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
    r = (sb.table("briefings")
         .select(f"id, date, created_at, {LANG_COL}")
         .order("created_at", desc=True).limit(1).execute())
    rows = r.data or []
    if not rows:
        print("run_critic: no briefings found.")
        return 2
    b = rows[0]
    text = b.get(LANG_COL) or ""
    config = _config()
    n_themes = critic.theme_count(text)
    cap = _cap(config, n_themes)
    findings = critic.critique(text, max_chars=cap, config=config)
    print(f"run_critic: brief={b['id']} date={b.get('date')} chars={len(text)} "
          f"themes={n_themes} cap={cap}")
    print(critic.format_report(findings))
    print(f"\nworst severity: {critic.worst_severity(findings) or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
