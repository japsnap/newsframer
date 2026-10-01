# NewsFramer

**Your own daily news brief, written by Claude on your Claude subscription, from the sources you choose.**
NewsFramer reads your RSS feeds every morning, drops duplicates and noise, scores each story against the topics you care about, and writes one themed brief with every source cited. You get it as a Markdown and JSON file to publish on your site, paste into a newsletter, or send to your phone.

**NewsFramerは、自分で選んだRSSを毎朝読み、Claude Code経由の自分のClaude Pro/Maxで日次ニュースブリーフを書く個人用ツールです。**
重複とノイズを除き、関心のあるトピックごとに記事を採点して、出典つきのテーマ別ブリーフにまとめます。出力はMarkdownとJSONなので、自分のサイトに公開したり、ニュースレターに貼ったり、スマホへ送ったりできます。

[A real brief](examples/brief-sample.md) · [Quickstart](#quickstart) · [Guide for AI coding agents](#for-ai-coding-agents) · ![tests](https://github.com/japsnap/newsframer/actions/workflows/tests.yml/badge.svg) (logic tests on Linux and Windows)

---

## Quickstart

Easiest path: open this repo in Claude Code or Codex and say *"Set up NewsFramer for me by following README.md"*. The agent section below tells it everything it needs.

By hand (PowerShell shown; on macOS or Linux use `python3 -m venv venv` and `source venv/bin/activate`):

```powershell
py -3.13 -m venv venv; .\venv\Scripts\Activate.ps1
pip install -r requirements.txt
npm install -g @anthropic-ai/claude-code   # then run `claude` once and sign in with your Claude plan
python setup_wizard.py                     # creates your config files and .env (asks for 2 Supabase values)
python manage.py db-init                   # creates the database tables
python manage.py sync                      # loads your sources and interests
python setup_check.py                      # PASS/FAIL for every part, including a live Claude call
python run_daily.py                        # builds today's brief into output/brief-<date>.md
```

You need: Python 3.13, a Claude Pro or Max plan with [Claude Code](https://docs.claude.com/en/docs/claude-code/overview), and a [Supabase](https://supabase.com) project (its smallest plan is enough). Everything else is optional.

---

## For AI coding agents

This section is written for Claude Code, Codex and similar agents setting up, adapting or extending NewsFramer for a user. Follow it literally.

### What the system is

A daily batch pipeline in Python 3.13. Each step is a standalone script under `agents/`; steps never call each other, Supabase (Postgres + pgvector) carries state between them, so any step can be re-run alone.

| Step | File | Does | AI |
|---|---|---|---|
| Fetch | `agents/fetcher.py` | RSS (and optional scrape) into `raw_articles`, per-source window and weekday calendar | none |
| Classify | `agents/classifier.py` | time-sensitive vs analysis label | Claude subscription |
| Deduplicate | `agents/deduplicator.py` | embeddings + clustering, soft-deletes copies | Gemini embeddings (optional; skipped without a key) |
| Analyze | `agents/analyst.py` | 0-10 relevance vs `user_context`, hypothesis labels | Claude subscription |
| Write | `agents/writer.py` | themed brief into `briefings` | Claude subscription |
| Save / deliver | `deliver_brief.py` | `output/brief-<date>.md` + `.json`, optional `post_brief_command`, optional send via OpenClaw | none |

`run_brief.py` runs the five steps; `run_daily.py` runs them and then `deliver_brief.py`. All AI calls go through headless Claude Code (`claude -p`, see `agents/cc_writer.py`); an API model is used only as a fallback, and every fallback is printed, logged to `logs/subscription-fallback.log` and alerted.

### Setup checklist (run in order, verify each)

1. Python 3.13 venv, `pip install -r requirements.txt`.
2. Claude Code installed (`claude --version`) and signed in by the user (`claude`, interactive; ask the user to do this step).
3. `python setup_wizard.py` creates `config/models.yaml`, `config/sources.yaml`, `config/interests.yaml` from the `*.example.yaml` templates and writes `.env`. Required in `.env`: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`. Optional: `SUPABASE_DB_URL` (for db-init; in Supabase: Connect > Connection string; use the **Session pooler** URI if the direct one fails, since the direct host is IPv6-only), `GEMINI_API_KEY` (dedup + fallback), `ANTHROPIC_API_KEY` (fallback), `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` (alerts), `DELIVERY_TARGET`, `FIRECRAWL_API_KEY`, `OPENCLAW_MJS`. Never ask the user to paste a key into chat; they type it into the wizard or `.env`.
4. Tables: `python manage.py db-init` (needs `SUPABASE_DB_URL`), or paste `sql/schema.sql` into the Supabase SQL editor. Safe to re-run.
5. Set `operator_timezone` in `config/models.yaml` (IANA name).
6. Edit `config/sources.yaml` and `config/interests.yaml` to the user's topics, then `python manage.py sync`.
7. `python setup_check.py` must print all PASS.
8. `python run_daily.py`, then open `output/brief-<date>.md` and confirm it has themes and cited links.
9. Schedule `python run_daily.py` daily (Task Scheduler, cron, or an OpenClaw cron).

### Recipes

| The user wants | Do this |
|---|---|
| A new topic (e.g. science) | Add sources with `category: science` to `config/sources.yaml`, add `science: 1` under `bundle_theme_floors` in `config/models.yaml`, run `python manage.py sync`. |
| A source removed | Set `active: false` on it in `config/sources.yaml`, then `sync`. Sync never deletes. |
| Stories ranked by their interests | Edit `config/interests.yaml` (`weight` -3..+3 per interest; hypotheses get confirm/challenge labels), then `sync`. |
| Shorter or longer themes | `surfaces.telegram.theme_size: S | M | L` in `config/models.yaml` (sizes in `theme_size_levels`). |
| More or fewer themes | `bundle_theme_floors`, `bundle_theme_cap`, `theme_count_multiplier`, `theme_count_max`. |
| A different tone or format | `prompts/writer/tone.txt`, `prompts/writer/format_rules.txt` (no numbers there; numbers come from config). |
| Publish to their website | Point `brief_output_dir` at the site's content folder, or set `post_brief_command: "python publish.py {md} {json}"` and write `publish.py`. The JSON holds the Markdown plus every cited article (title, url, source, category). |
| The brief on their phone | Install [OpenClaw](https://docs.openclaw.ai/), connect a channel ([list](https://docs.openclaw.ai/channels)), set `delivery_channel` + `delivery_account` in config and `DELIVERY_TARGET` in `.env`, test with `python deliver_brief.py --dry-run`. |
| Several WhatsApp chats, per-chat topics and languages | Copy `config/whatsapp_deliveries.example.yaml` to `config/whatsapp_deliveries.yaml`, run `python run_whatsapp_brief.py` (dry) then `--send`. |
| A step off the subscription | `<step>_use_subscription: false` (steps: classifier, analyst, title_dedup, writer, drop_report, sequencing, whatsapp); that step then needs its API key. |
| Use the brief inside their own app | Read `output/brief-<date>.json`, or query the `briefings` table (`content_en`, `article_ids`). |

### Rules that keep it working

- **Config only.** Every number lives in `config/models.yaml`, read with `config.get(key, default)`. Never put a tunable in code or in a prompt file. A new key goes into `config/models.example.yaml` too.
- **Subscription first.** Do not switch steps to a metered API by default. Fallbacks must stay loud (`cc_writer.notify_fallback`).
- **Soft-delete only.** Articles are never hard-deleted; dedup sets `deleted_at`.
- **Delivery is recorded only after a confirmed send** (`agents/deliver.py`), or after the file is saved in file-only mode. This is how tomorrow's brief knows what is new.
- **Facts come from articles.** The writer summarises source articles with citations; it never rewrites a previous brief.
- **Secrets stay in `.env`.** Never print, log or commit a key. `git config core.hooksPath hooks` turns on the pre-commit key guard.
- **Tests:** `python tests/run_all.py` (no database or AI calls) must stay green; add a test with every change.

### File map

```
run_daily.py            build + save + deliver (the daily job)
run_brief.py            build only (the five steps)
deliver_brief.py        save .md/.json, post_brief_command, optional OpenClaw send
run_whatsapp_brief.py   per-chat WhatsApp briefs
manage.py               db-init | sync | sources
setup_wizard.py         first-run config + .env;   setup_check.py  the install check
check_run_health.py     missed-run watchdog;       gateway_watchdog.py  OpenClaw gateway watchdog (Windows)
agents/                 the steps + cc_writer.py (subscription routing), llm_client.py (timeouts,
                        fallback), deliver.py, operator_tz.py, bundle_floors.py, drop_reports.py,
                        thread_tracker.py ("What Changed"), critic.py, surface_render.py, ...
config/*.example.yaml   templates for models (all settings), sources, interests, WhatsApp chats
prompts/                analyst and writer prompts
sql/schema.sql          full schema (RLS on, service-role access only); sql/seed_*.sql starter data
examples/               a real sample brief
tests/                  run_all.py + one file per module
```

### Cost and quota

AI work uses the Claude plan's quota instead of a per-call bill. With the starter sources a run makes roughly 50 to 100 short `claude -p` calls (about 20 scoring batches of 10 articles, a similar number of classify batches, one write, a few summaries); a large source list needs a Max plan. The `execution_log` table records every step's model and tokens per run.

## What's new

- **2026-10-01.** Sources and interests as YAML files with `manage.py sync`; one-command database setup (`manage.py db-init`); a JSON copy of every brief and an optional post-save command for publishing; works on macOS and Linux; row-level security on every table; tests run on GitHub for Linux and Windows.
- **2026-09-29, first public release.** Every AI step runs on a Claude subscription, with an alert whenever an API fallback is used; the brief is always saved as a file and phone delivery is optional; timezone set by name.

## License

MIT (see `LICENSE`).
