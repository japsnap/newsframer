"""
NewsFramer guided first-run setup.

Asks for your keys one at a time and writes them into a fresh `.env` — the conversational
alternative to copying `.env.example` by hand. Safe by design:

  - It will NEVER touch an existing .env (it refuses and exits; edit that file directly instead).
  - It never prints a value back to the screen — variable names only.
  - It changes nothing else: no database writes, no network calls. When it finishes it tells you
    the next two commands (load sql/schema.sql in Supabase if you haven't, then setup_check.py).

Usage:  python setup_wizard.py
"""
import os
import sys

try:  # Windows consoles default to cp1252 and garble the dashes in prompts.
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# (name, one-line hint shown at the prompt). Order = the order the wizard asks.
REQUIRED = [
    ("SUPABASE_URL", "your Supabase project URL, e.g. https://xxxx.supabase.co (Settings > API)"),
    ("SUPABASE_SERVICE_KEY", "the service_role secret key (Settings > API > service_role)"),
    ("GEMINI_API_KEY", "Google AI Studio key (aistudio.google.com > Get API key)"),
    ("TELEGRAM_BOT_TOKEN", "from @BotFather after /newbot, looks like 123456789:AA..."),
    ("TELEGRAM_CHAT_ID", "your numeric chat id (message @userinfobot to see it)"),
]
OPTIONAL = [
    ("ANTHROPIC_API_KEY", "only if you want Claude models via the metered API (Enter to skip)"),
    ("FIRECRAWL_API_KEY", "only for the no-RSS scrape sources (free tier is fine; Enter to skip)"),
    ("OPENCLAW_MJS", "path to openclaw.mjs if not in the default npm location (Enter to skip)"),
]


def build_env_content(answers):
    """Render the .env text from {name: value}. Pure. Required vars first (wizard order),
    then any answered optionals; blank/missing values are omitted entirely."""
    lines = ["# NewsFramer .env — written by setup_wizard.py (names documented in .env.example)"]
    for name, _hint in REQUIRED + OPTIONAL:
        v = (answers.get(name) or "").strip()
        if v:
            lines.append(f"{name}={v}")
    return "\n".join(lines) + "\n"


def _light_warnings(name, value):
    """Warn-only sanity notes for a value that LOOKS wrong (never blocks — providers change
    formats, and the operator knows their own keys). Returns a list of warning strings that
    never include the value itself."""
    warns = []
    if name == "SUPABASE_URL" and not (value.startswith("https://") and "supabase" in value):
        warns.append(f"  WARN: {name} looks unusual (expected https://<project>.supabase.co) — kept as entered.")
    if name == "TELEGRAM_CHAT_ID" and not value.lstrip("-").isdigit():
        warns.append(f"  WARN: {name} looks unusual (expected a number) — kept as entered.")
    if name == "TELEGRAM_BOT_TOKEN" and ":" not in value:
        warns.append(f"  WARN: {name} looks unusual (expected <digits>:<letters>) — kept as entered.")
    return warns


def run_wizard(base_dir=None, input_fn=input, print_fn=print):
    """Interactive flow. base_dir/input_fn/print_fn are injectable so tests run in a tempdir
    against scripted answers — the real .env is never in a test's reach."""
    base = base_dir or os.path.dirname(os.path.abspath(__file__))
    env_path = os.path.join(base, ".env")
    if os.path.exists(env_path):
        print_fn("A .env file already exists here — the wizard never overwrites it.")
        print_fn(f"Edit it directly instead (variable names are documented in .env.example): {env_path}")
        return 1

    print_fn("NewsFramer setup — I'll ask for each key, then write .env for you.")
    print_fn("Paste each value and press Enter. Values are stored in .env only, never shown back.")
    answers = {}
    for name, hint in REQUIRED:
        print_fn(f"\n{name} — {hint}")
        v = ""
        while not v.strip():
            v = input_fn(f"{name}: ")
            if not v.strip():
                print_fn("  This one is required — please paste a value.")
        answers[name] = v.strip()
        for w in _light_warnings(name, answers[name]):
            print_fn(w)
    print_fn("\nOptional keys (press Enter to skip any of them):")
    for name, hint in OPTIONAL:
        print_fn(f"\n{name} — {hint}")
        answers[name] = input_fn(f"{name} (optional): ").strip()

    with open(env_path, "w", encoding="utf-8") as f:
        f.write(build_env_content(answers))
    written = [n for n, _ in REQUIRED + OPTIONAL if (answers.get(n) or "").strip()]
    print_fn(f"\nWrote {env_path} with: {', '.join(written)}")
    print_fn("\nNext steps:")
    print_fn("  1. If you haven't yet: run sql/schema.sql then the sql/seed_*.sql files in the")
    print_fn("     Supabase SQL editor (one paste each).")
    print_fn("  2. python setup_check.py   <- verifies everything is reachable before the first run")
    print_fn("  3. python run_brief.py     <- your first brief (prints to the console)")
    return 0


if __name__ == "__main__":
    sys.exit(run_wizard())
