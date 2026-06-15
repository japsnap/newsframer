# NewsFramer

A personal news automation bot. Every day it pulls articles from your RSS sources, classifies and deduplicates them, scores them against your interests and tracked hypotheses, synthesizes a themed briefing, and delivers it to Telegram and WhatsApp.

Personal tool. Low cost. Single operator. **Fully config-driven** — you tune it by editing `config/models.yaml` and a few prompt files, never the source.

## What it does

**Fetch → Classify → Deduplicate → Analyze → Write → Deliver**, on a daily schedule orchestrated by OpenClaw:

1. **Fetch** — pulls articles from your configured RSS sources, honoring a per-source freshness window and a distributed weekly scrape calendar so low-frequency sources aren't missed. Each source carries a weight and a per-source article cap; the total is bounded only by a high safety ceiling. Falls back to the OpenClaw browser / Firecrawl skill for JS-heavy or non-RSS pages.
2. **Classify** — labels each article `IMMEDIATE` (time-sensitive) or `KEEP_WARM` (analytical), and flags intra-batch duplicates.
3. **Deduplicate** — embeddings + clustering; soft-deletes duplicates, keeping the originator (analysis) or the latest update (price events), and stamps a `cluster_id` so same-story copies stay linked.
4. **Analyze** — scores each article 0–10 against the interests and hypotheses you've stored in Supabase; labels each as confirming, challenging, a new signal, or neutral. The relevance score is the signal/noise gate — it's what keeps sports scores and shopping guides out of a serious brief.
5. **Write** — synthesizes the top-scoring articles into a themed briefing with a Highlights section. Each topic bundle (crypto, geopolitics, Pakistan, cybersecurity, tech, VC, …) is guaranteed a **minimum presence** and capped at a maximum, so a high-volume bundle can't crowd out a quiet one; the theme count scales with how many bundles are active that day.
6. **Deliver** — two daily slots: a **Telegram** brief (you) in the morning, and a topic-filtered, multi-language **WhatsApp** brief (groups / a second number) later in the day. Article IDs are recorded as delivered **only after a confirmed send**, so "what's new" stays accurate and a failed send never marks anything delivered.

Also:

- **Second-slot freshness** — before the later WhatsApp slot builds, it gap-fetches the news published since the morning run (fetch → classify → dedup → analyze on the new articles only) and weights fresh items so genuinely new stories surface — the second brief is never just a re-filtered copy of the first.
- **Investigative drop-reports** — articles from curated OSINT / investigative sources surface as a distinct **🔍 Investigations** section, woven into the day's main theme when relevant and expandable on request.
- **Optional pre-analysis title-dedup** — when global wire feeds pile 5–9 near-identical copies of one event into the pool, an optional stage reuses the deduplicator's clusters and a cheap titles-only LLM confirm to collapse them to the originator before the (paid) analysis. Off by default.
- **Optional pre-send critic** — a deterministic checker can review a finished brief for empty sections, missing citations, or character overruns before delivery. Off by default.
- **Seasonal modules** — self-contained, time-boxed add-ons (e.g. a daily World Cup update built from public structured data) that deliver to a chat and self-skip when there's nothing to report or the season ends.
- **Run-health watchdog** — a short grace window after each run, it checks the run's artifacts in the database and pings you if a stage went partial/failed, no fresh brief was produced, or the run didn't fire at all.

## Architecture

- **Conductor / runtime:** OpenClaw (`openclaw.ai`) on an always-on PC — schedules the daily runs (cron + a weekly Monday hard reset), runs the engines, and delivers the brief.
- **Engines:** five standalone Python modules under `agents/` — `fetcher`, `classifier`, `deduplicator`, `analyst`, `writer`. No engine calls another in code; Supabase carries state between them, so each is re-runnable in isolation.
- **Supporting modules:** `agents/deliver.py` (confirmed-send delivery + recording), `drop_reports.py` (Investigations), `bundle_floors.py` (per-bundle theme allocation), `title_dedup.py` (optional same-story collapse), `critic.py` (optional pre-send check), `char_monitor.py` (character-overrun flag), `brief_select.py` (pick the most-complete fresh brief), `worldcup_data.py` / `worldcup_format.py` (the seasonal World Cup module), `llm_json.py` (tolerant LLM-JSON parsing), `run_log.py` (best-effort run logging).
- **Data:** Supabase (Postgres + pgvector) — articles, classifications, embeddings, scores, briefings, deliveries, run logs, sources, hypotheses.
- **Models:** Gemini 2.5 Flash-Lite for the cheap stages (classify / analyze / embed / title-dedup), Claude Haiku for synthesis. Every model choice lives in `config/models.yaml`; no model IDs in code.
- **Delivery:** Telegram Bot API + WhatsApp (a second dedicated number), through the OpenClaw gateway, which returns a real message ID used to gate the delivery recording.

Each engine documents itself in its module docstring; `config/models.yaml` is the single tunable surface.

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
├── README.md / CHANGELOG.md           this file + the dated record of what ships
├── run_brief.py                       daily pipeline (5 engines, no dispatcher) -> brief in Supabase
├── run_daily.py                       build + deliver the Telegram brief in ONE process (the morning job)
├── deliver_brief.py                   send the fresh brief to Telegram + record deliveries ON confirmed send
├── run_whatsapp_brief.py              per-chat WhatsApp briefs (topic-filtered, multi-language); 2nd-slot
│                                      gap-fetch refresh; per-chat recording on confirmed send
├── run_worldcup_brief.py              seasonal World Cup update (structured data) -> WhatsApp, self-skips
├── run_pipeline.py                    legacy full pipeline (manual local runs only)
├── run_critic.py                      run the (optional) pre-send critic over the latest brief — inspect only
├── check_run_health.py               missed-run / partial-run watchdog (alerts via the Telegram bot)
├── record_deliveries.py               record a brief's article IDs as delivered (idempotent)
├── print_latest_brief.py              print the latest fresh brief to stdout
├── get_drop_report.py                 return the full write-up for a drop-report on "more: <slug>"
├── eval_classifier.py                 standalone Classifier inspection script
├── requirements.txt                   Python dependencies
├── agents/
│   ├── fetcher.py classifier.py deduplicator.py analyst.py writer.py   (the 5 engines)
│   ├── deliver.py                     confirmed-send delivery seam (record only after a real messageId)
│   ├── drop_reports.py                investigative drop-report logic (Investigations section)
│   ├── bundle_floors.py               per-bundle theme allocation (floors + caps)
│   ├── title_dedup.py                 OPTIONAL: collapse same-story wire copies before the analyst
│   ├── critic.py                      OPTIONAL: deterministic pre-send brief check (never patches)
│   ├── char_monitor.py                flags a brief that exceeds its theme-scaled character cap
│   ├── brief_select.py                pick today's most-complete fresh brief for delivery
│   ├── worldcup_data.py worldcup_format.py   seasonal World Cup module (parse + format)
│   ├── llm_json.py                    tolerant LLM-JSON parsing (object/array/string/null, fences, prose)
│   ├── run_log.py                     best-effort agent_runs logging
│   └── dispatcher.py                  DEPRECATED — superseded by OpenClaw delivery; kept only for reference
├── config/
│   ├── models.yaml                    every tunable (single config surface)
│   └── whatsapp_deliveries.example.yaml   per-chat registry template (the real one is gitignored)
├── prompts/
│   ├── analyst/system_prompt.txt
│   └── writer/{system_prompt,tone,format_rules}.txt
├── tests/                             unit tests (pure logic — no live DB or LLM)
├── *.sql / user_context.example.*     example schema / one-off data migrations
├── .env.example                       environment-variable template
└── venv/                              local virtualenv (gitignored)
```

## Configuration

**Nothing operational is hardcoded.** Every tunable — model selection, per-source and total article caps, character/length limits, theme & highlight counts, the relevance threshold, batch sizes, LLM temperature/max-tokens, windows, retries, message limits — lives in `config/models.yaml` and is read with a safe default, so changing your topic set or scale only means editing the config. The prompt files describe *behavior*; the *numbers* are injected from config.

| What | Where |
|------|-------|
| Models, thresholds, windows, counts, caps, limits, pricing — **all tunables** | `config/models.yaml` |
| Analyst scoring behavior | `prompts/analyst/system_prompt.txt` |
| Briefing tone | `prompts/writer/tone.txt` |
| Briefing structure / title casing / citation rules | `prompts/writer/format_rules.txt` |
| Operator interests + hypotheses | `user_context` table (Supabase) |
| RSS sources, bundles, region/Ground-News tags, per-source window + scrape calendar + weight | `sources` table (Supabase) |
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

# Morning job — build today's brief into Supabase and deliver it to Telegram in one process:
python run_daily.py                # --dry-run to preview deliver chunks without rebuilding

# Or build and deliver as separate steps:
python run_brief.py                # the 5 engines -> brief in Supabase
python deliver_brief.py            # --dry-run to preview chunks

# Later slot — per-chat WhatsApp briefs (gap-refreshes the pool first when sending):
python run_whatsapp_brief.py       # dry run (generate + save, no send)
python run_whatsapp_brief.py --send

# Seasonal World Cup update (self-skips when there's nothing to report):
python run_worldcup_brief.py       # dry run (fetch + build + print)

# Health watchdog (run after a slot's grace window):
python check_run_health.py --slot telegram --dry-run

# Or run a single engine in isolation:
python agents\classifier.py
python agents\deduplicator.py --apply
python agents\title_dedup.py       # dry; --apply collapses; --all inspects the whole window
python eval_classifier.py          # inspection-only, after classifier.py
```

## Cost

Designed to run cheap:

- Cheap models for skim / classify / dedup / analyze; the writer-grade model only for synthesis.
- Opus off by default. Sonnet sparingly.
- USD $2/day is a disaster cap, not a target.

## Scope

Personal tool, no public guarantees. Treat any code, prompt, or configuration here as evolving.
