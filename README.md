# NewsFramer

A personal news automation bot. Every day it pulls articles from your RSS sources, classifies and deduplicates them, scores them against your interests and tracked hypotheses, synthesizes a themed briefing, and delivers it to Telegram and WhatsApp.

Personal tool. Low cost. Single operator. **Fully config-driven** — you tune it by editing `config/models.yaml` and a few prompt files, never the source.

## What it does

**Fetch → Classify → Deduplicate → Analyze → Write → Deliver**, daily, orchestrated by OpenClaw:

1. **Fetch** — pulls articles from your configured RSS sources, honoring a per-source freshness window and a distributed weekly scrape calendar so low-frequency sources aren't missed. Falls back to the OpenClaw browser / Firecrawl skill for JS-heavy or non-RSS pages.
2. **Classify** — labels each article `IMMEDIATE` (time-sensitive) or `KEEP_WARM` (analytical), and flags intra-batch duplicates.
3. **Deduplicate** — embeddings + clustering; soft-deletes duplicates, keeping the originator (analysis) or the latest update (price events).
4. **Analyze** — scores each article 0–10 against the interests and hypotheses you've stored in Supabase; labels each as confirming, challenging, a new signal, or neutral.
5. **Write** — synthesizes the top-scoring articles into a themed briefing with a Highlights section. Each topic bundle (crypto, geopolitics, Pakistan, cybersecurity, tech, …) is guaranteed a **minimum presence**, so a high-volume bundle can't crowd out a quiet one.
6. **Deliver** — sends the brief to Telegram (you) and WhatsApp (a second number). Article IDs are recorded as delivered **only after a confirmed send**, so "what's new" stays accurate and a failed send never marks anything delivered.

Also:

- **Investigative drop-reports** — articles from curated OSINT / investigative sources surface as a distinct **🔍 Investigations** section, woven into the day's main theme when relevant and expandable on request.
- **Run-health watchdog** — a short grace window after each run, it checks the run's artifacts in the database and pings you if a stage went partial/failed, no fresh brief was produced, or the run didn't fire at all.

## Architecture

- **Conductor / runtime:** OpenClaw (`openclaw.ai`) on an always-on PC — schedules the daily runs (cron + a weekly Monday hard reset), runs the engines, and delivers the brief.
- **Engines:** five standalone Python modules under `agents/` — `fetcher`, `classifier`, `deduplicator`, `analyst`, `writer`. No engine calls another in code; Supabase carries state between them, so each is re-runnable in isolation.
- **Supporting modules:** `agents/deliver.py` (confirmed-send delivery + recording), `drop_reports.py`, `bundle_floors.py`, `llm_json.py` (tolerant LLM-JSON parsing), `run_log.py` (best-effort run logging).
- **Data:** Supabase (Postgres + pgvector) — articles, classifications, embeddings, scores, briefings, deliveries, run logs, sources, hypotheses.
- **Models:** Gemini 2.5 Flash-Lite for the cheap stages, Claude Haiku for synthesis. Every model choice lives in `config/models.yaml`; no model IDs in code.
- **Delivery:** Telegram Bot API + WhatsApp (second dedicated number), through the OpenClaw gateway.

See `AGENTS.md` for the per-engine reference and `CLAUDE.md` for the working agreement that governs any AI assistant editing this repo.

## Prerequisites

- Python 3.13+ on Windows (PowerShell is the working shell).
- A Supabase project (Postgres + pgvector) — ideally one dedicated to NewsFramer.
- API keys: Google AI Studio (Gemini) and Anthropic (Claude), used via LiteLLM.
- A Telegram bot token + your own chat ID.
- WhatsApp on a dedicated second number (paired to OpenClaw via QR).
- OpenClaw installed and running on the always-on PC.

## Repo layout

```
newsframer/
├── README.md / AGENTS.md            this file + the per-engine reference
├── run_brief.py                     daily pipeline (5 engines, no dispatcher) -> brief in Supabase
├── deliver_brief.py                 send the fresh brief to Telegram + record deliveries ON confirmed send
├── run_whatsapp_brief.py            per-chat WhatsApp briefs (topic-filtered, multi-language) + per-chat recording
├── run_pipeline.py                  legacy full pipeline (manual local runs only)
├── check_run_health.py              missed-run / partial-run watchdog (alerts via the Telegram bot)
├── record_deliveries.py             record a brief's article IDs as delivered (idempotent)
├── print_latest_brief.py            print the latest fresh brief to stdout
├── get_drop_report.py               return the full write-up for a drop-report on "more: <slug>"
├── eval_classifier.py               standalone Classifier inspection script
├── agents/
│   ├── fetcher.py classifier.py deduplicator.py analyst.py writer.py   (the 5 engines)
│   ├── deliver.py                   confirmed-send delivery seam (record only after a real messageId)
│   ├── drop_reports.py              investigative drop-report logic
│   ├── bundle_floors.py             per-bundle theme allocation (floors + caps)
│   ├── llm_json.py                  tolerant LLM-JSON parsing (object/array/string/null, fences, prose)
│   └── run_log.py                   best-effort agent_runs logging
│   └── dispatcher.py                DEPRECATED — superseded by OpenClaw delivery; kept only for reference
├── config/
│   ├── models.yaml                  every tunable (single config surface)
│   └── whatsapp_deliveries.example.yaml   per-chat registry template (the real one is gitignored)
├── prompts/
│   ├── analyst/system_prompt.txt
│   └── writer/{system_prompt,tone,format_rules}.txt
├── tests/                           unit tests (pure logic — no live DB or LLM)
├── .env.example                     environment-variable template
└── venv/                            local virtualenv (gitignored)
```

## Configuration

**Nothing operational is hardcoded.** Every tunable — model selection, character/length limits, theme & highlight counts, batch sizes, LLM temperature/max-tokens, windows, retries, message limits — lives in `config/models.yaml` and is read with a safe default, so changing your topic set or scale only means editing the config. The prompt files describe *behavior*; the *numbers* are injected from config.

| What | Where |
|------|-------|
| Models, thresholds, windows, counts, limits, pricing — **all tunables** | `config/models.yaml` |
| Analyst scoring behavior | `prompts/analyst/system_prompt.txt` |
| Briefing tone | `prompts/writer/tone.txt` |
| Briefing structure / title casing / citation rules | `prompts/writer/format_rules.txt` |
| Operator interests + hypotheses | `user_context` table (Supabase) |
| RSS sources, bundles, region/Ground-News tags, per-source window + scrape calendar | `sources` table (Supabase) |
| WhatsApp per-chat delivery registry (group JIDs + DM numbers) — **gitignored** | `config/whatsapp_deliveries.yaml` (template `*.example.yaml`) |
| Junk URL / title filters | `junk_patterns` table (Supabase) |
| Scheduling, Skill wiring, Telegram / WhatsApp delivery | OpenClaw config (out of repo) |

## Secrets

Credentials live in `.env` (copy `.env.example` and fill it in) and are read by every engine via `python-dotenv`. The engines read `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, the Telegram bot token + chat ID, and the provider API keys consumed by LiteLLM.

`.env`, any `*.env`, `*.key`, `*.pem`, and the real `config/whatsapp_deliveries.yaml` are gitignored. **Never commit credentials. Never paste keys into chat with an AI assistant — it does not need them.**

## Running

In production OpenClaw schedules everything. To run by hand from PowerShell (testing / recovery):

```powershell
.\venv\Scripts\Activate.ps1

# Build today's brief into Supabase (the 5 engines, no dispatcher):
python run_brief.py

# Deliver it to Telegram and record deliveries only on a confirmed send:
python deliver_brief.py            # --dry-run to preview chunks; --simulate-fail to test the alert path

# Per-chat WhatsApp briefs:
python run_whatsapp_brief.py       # dry run (generate + save, no send)
python run_whatsapp_brief.py --send

# Health watchdog (run after a slot's grace window):
python check_run_health.py --slot telegram --dry-run

# Or run a single engine in isolation:
python agents\classifier.py
python agents\deduplicator.py --apply
python eval_classifier.py          # inspection-only, after classifier.py
```

## Cost

Designed to run cheap:

- Cheap models for skim / classify / dedup; the writer-grade model only for synthesis.
- Opus off by default. Sonnet sparingly.
- USD $2/day is a disaster cap, not a target.

## Scope

Personal tool, no public guarantees. Treat any code, prompt, or configuration here as evolving; `CLAUDE.md` is the binding working agreement for collaborators.
