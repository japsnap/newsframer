# NewsFramer

A personal news desk that runs on your Claude subscription. Every day it reads the RSS feeds you choose, drops duplicates and noise, scores each article against the topics you care about, and writes one themed briefing with sources. You get it as a Markdown file you can read, paste into your website or newsletter, or (optionally) receive on your phone.

- **No API bill by default.** Every AI step runs through headless Claude Code (`claude -p`) on your Claude Pro or Max plan. API keys are an optional fallback, and you are told whenever the fallback is used.
- **Everything is configurable.** Topics, sources, length, tone, timezone, schedule and delivery live in config files and a database table, not in the code.
- **Phone delivery is optional.** Telegram, WhatsApp, Discord, Slack, Signal, iMessage and more through [OpenClaw](https://docs.openclaw.ai/), or none at all.

## How it works

**Fetch → Classify → Deduplicate → Analyze → Write → Save / Deliver**

1. **Fetch** pulls new articles from your sources (RSS, plus an optional scrape path for sites without a feed), honouring a per-source time window and weekly schedule.
2. **Classify** labels each article as time-sensitive or slower analysis.
3. **Deduplicate** clusters copies of the same story and keeps the original (needs the optional Gemini key; skipped without it).
4. **Analyze** scores each article 0–10 against your interests and tracked hypotheses and marks whether it confirms, challenges or adds to them. Low scores are the noise filter.
5. **Write** groups the best articles into themes with a Highlights section and cited sources. Every topic bundle gets a guaranteed minimum and a cap, so a loud topic cannot crowd out a quiet one.
6. **Save / Deliver** writes `output/brief-<date>.md` and, if you set a channel, sends it. Articles count as "already delivered" only after a confirmed send (or a saved file in file-only mode), so tomorrow's brief shows only what is new.

Optional extras, each switchable in the settings file: an **Investigations** section for OSINT and investigative sources; **What Changed** notes when a tracked story's key number moves day over day; a **Blindspot of the Day** line; a pre-send **critic** that flags empty sections or missing citations; per-chat WhatsApp briefs in several languages; a run-health watchdog that alerts you if a daily run is missed.

## What you need

| | Needed? | What for |
|---|---|---|
| Python 3.13 | Yes | runs the pipeline (developed on Windows; paths are portable) |
| Claude Pro or Max plan + [Claude Code](https://docs.claude.com/en/docs/claude-code) | Yes | every AI step. A daily run with the starter sources makes roughly 50–100 short calls (about 20 scoring batches of 10 articles, a similar number of classify batches, one write, a few summaries) |
| [Supabase](https://supabase.com) project (free tier) | Yes | stores articles, scores and briefs between steps |
| Gemini API key (free tier) | Optional | duplicate detection, and the fallback when a subscription call fails |
| [OpenClaw](https://docs.openclaw.ai/) | Optional | sending the brief to a phone or chat app, and scheduled runs |
| Telegram bot | Optional | alerts (missed run, fallback to API, failed send) |
| Firecrawl key | Optional | better scraping for sites without RSS |

## Quickstart

In a terminal (PowerShell on Windows):

1. Clone this repo and open a terminal in it.
2. Create the environment and install:
   ```powershell
   py -3.13 -m venv venv
   .\venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```
3. Install Claude Code and sign in once with your Claude plan:
   ```powershell
   npm install -g @anthropic-ai/claude-code
   claude
   ```
   (Type `/exit` after signing in.)
4. Create a Supabase project. In its SQL editor run `sql/schema.sql`, then `sql/seed_sources.sql` and `sql/seed_junk_patterns.sql`. Edit `sql/seed_user_context.example.sql` to describe your own interests and run it (optional; the pipeline works without it).
5. Run `python setup_wizard.py`. It creates your settings file `config/models.yaml` from the template, checks Claude Code, and asks for your keys (only the two Supabase values are required) to write `.env`. It never overwrites an existing `.env` and never shows a value back.
6. Open `config/models.yaml` and set `operator_timezone` (for example `"Europe/London"`).
7. Run `python setup_check.py`. It checks the settings file, `.env`, Supabase, the tables, one RSS fetch, the optional Gemini key and a live answer from your Claude subscription, printing PASS or FAIL for each.
8. Run `python run_daily.py`. It builds today's brief and saves it to `output/brief-<date>.md`.

Prefer a guided walk-through? Paste the prompt in `SETUP_PROMPT.md` into Claude and it takes you through these steps one at a time.

## Getting your brief

**As a file (default).** Each run writes `output/brief-<date>.md`. Change the folder with `brief_output_dir`. Point it at your website's content folder to publish it, or read it in any Markdown app.

**On your phone (optional).** Install OpenClaw, connect the channel you want (see the [OpenClaw channel guides](https://docs.openclaw.ai/channels)), then in `config/models.yaml` set:
```yaml
delivery_channel: "telegram"      # or whatsapp, discord, slack, signal, imessage, ... (the channel id from the OpenClaw docs)
delivery_account: "default"       # the OpenClaw account id for that channel
```
and put the recipient (chat id, phone number or channel id) in `.env` as `DELIVERY_TARGET`. The file is still saved either way.

**Several WhatsApp chats with different topics and languages.** Copy `config/whatsapp_deliveries.example.yaml` to `config/whatsapp_deliveries.yaml`, list the chats, and run `python run_whatsapp_brief.py --send`.

## Running it every day

Any scheduler works; the job is one command, `python run_daily.py`, from the repo folder with the venv's Python.

- **OpenClaw cron** (if you use OpenClaw for delivery): add a daily job that runs `run_daily.py`, and one for `check_run_health.py --slot telegram` about 30 minutes later.
- **Windows Task Scheduler**: a daily task running `venv\Scripts\python.exe run_daily.py` with the repo as its start folder.
- **cron (macOS / Linux)**: `0 6 * * * cd /path/to/newsframer && venv/bin/python run_daily.py`.

The computer has to be on at that time. Claude Code must be signed in for the account the task runs under.

## Cost and the subscription

- By default every AI step uses your Claude plan (`use_subscription: true`), so a normal run has **no metered cost**.
- If a subscription call fails (plan limit reached, signed out, Claude Code missing), that step falls back to its API model, but only if you added that provider's key. With no key, the step fails and the run reports it.
- **Every fallback is reported by default**: printed, written to `logs/subscription-fallback.log`, and sent as an alert if you set up the Telegram alert bot. Turn the alert off with `notify_on_subscription_fallback: false`.
- Switch one step off the subscription with `<step>_use_subscription: false` (steps: `classifier`, `analyst`, `title_dedup`, `writer`, `drop_report`, `sequencing`, `whatsapp`).
- The `execution_log` table records each step's model, tokens and cost per run (subscription calls are recorded as $0). `cost_report_cap_usd` only adds a "% of cap" line to the daily cost report; it does not stop anything.

## Make it yours

| What | Where |
|---|---|
| Every setting (models, timezone, output, delivery, theme counts, length, windows, thresholds) | `config/models.yaml` (your copy of `config/models.example.yaml`; never committed) |
| Your sources and topic bundles | `sources` table in Supabase (starter set: `sql/seed_sources.sql`). A bundle is just the `category` text, so adding `'science'` rows creates a science bundle; give it a floor in `bundle_theme_floors` |
| Your interests and hypotheses | `user_context` table (template: `sql/seed_user_context.example.sql`) |
| Scoring behaviour | `prompts/analyst/system_prompt.txt` |
| Tone and format of the brief | `prompts/writer/tone.txt`, `prompts/writer/format_rules.txt` |
| URL and title junk filters | `junk_patterns` table (starter set: `sql/seed_junk_patterns.sql`) |
| WhatsApp chats | `config/whatsapp_deliveries.yaml` (template `*.example.yaml`; never committed) |
| Keys | `.env` (never committed) |

Numbers never live in the prompt files or the code; they are read from the settings file with safe defaults.

## Commands

```powershell
python setup_check.py                 # verify the install (--offline skips network calls)
python run_daily.py                   # build today's brief, save it, deliver it if a channel is set
python run_brief.py                   # build only
python deliver_brief.py --dry-run     # preview what would be saved or sent
python print_latest_brief.py          # print the latest brief
python run_whatsapp_brief.py --send   # per-chat WhatsApp briefs
python check_run_health.py --slot telegram --dry-run   # the missed-run watchdog
python agents\classifier.py           # run any single step on its own
python tests\run_all.py               # the test suite (no database or AI calls)
```

## Repo layout

```
newsframer/
├── run_daily.py, run_brief.py, deliver_brief.py     build, save, deliver
├── run_whatsapp_brief.py                           per-chat WhatsApp briefs
├── setup_wizard.py, setup_check.py                 first-run setup and the install check
├── check_run_health.py, gateway_watchdog.py        watchdogs (missed runs; OpenClaw gateway down)
├── agents/                                         the five steps + helpers
│   ├── fetcher.py classifier.py deduplicator.py analyst.py writer.py
│   ├── cc_writer.py        Claude subscription routing (claude -p), fallback + its alert
│   ├── llm_client.py       timeouts, API fallback, circuit breaker
│   ├── deliver.py          confirmed-send delivery and alerts
│   ├── operator_tz.py      your timezone
│   └── ...                 theme floors, investigations, critic, story tracking, rendering
├── config/models.example.yaml                      settings template (copy to models.yaml)
├── config/*.example.yaml                           WhatsApp and chat-reply templates
├── prompts/                                        analyst and writer prompts
├── sql/                                            schema + starter data
├── tests/                                          unit tests
└── hooks/pre-commit                                blocks commits that contain keys
```

## Secrets and privacy

Keys live only in `.env`. `.env`, `config/models.yaml`, `config/whatsapp_deliveries.yaml`, `output/` and `logs/` are git-ignored. Turn on the commit guard with `git config core.hooksPath hooks`; it refuses a commit that stages a key file or key-shaped text. Never paste a key into a chat with an AI assistant; it does not need one.

## What's new

- **2026-09-29, public release.** Every AI step can run on a Claude subscription, with an alert whenever the API fallback is used. The brief is always saved as a Markdown file and phone delivery is optional, through any channel OpenClaw supports. Timezone is set by name, so daylight saving is handled. Only the two Supabase keys are required. Settings now ship as a template (`config/models.example.yaml`).

## License

MIT (see `LICENSE`). A personal project shared as is; expect changes.
