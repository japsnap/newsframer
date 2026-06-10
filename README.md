# NewsFramer

A personal news automation pipeline. Pulls articles from your RSS sources every day, classifies and deduplicates them, scores them against your interests and tracked hypotheses, synthesizes a themed briefing, and delivers it to Telegram and WhatsApp.

This is a personal tool. Low cost. Single operator.

## What it does

1. **Fetch** — pulls articles from your configured RSS sources. Falls back to the OpenClaw browser / Firecrawl skill for JS-heavy or non-RSS pages.
2. **Classify** — labels each article `IMMEDIATE` (time-sensitive) or `KEEP_WARM` (analytical).
3. **Deduplicate** — embeddings + clustering; soft-deletes duplicates, keeps the originator (analysis) or the latest update (price events).
4. **Analyze** — scores each article 0–10 against the interests and hypotheses you've stored in Supabase; labels each as confirming, challenging, a new signal, or neutral.
5. **Write** — synthesizes the top-scoring articles into a themed briefing.
6. **Deliver** — OpenClaw sends the brief to Telegram (you) and WhatsApp (your second number).

## Architecture

- **Conductor / runtime:** OpenClaw (`openclaw.ai`) on an always-on PC. Schedules pipeline runs, invokes the engines as Skills, and delivers the brief.
- **Engines:** five Python modules under `agents/` — `fetcher.py`, `classifier.py`, `deduplicator.py`, `analyst.py`, `writer.py`. Each is independently runnable; Supabase is the orchestration substrate between them.
- **Data:** Supabase (Postgres + pgvector) — articles, classifications, embeddings, scores, briefings, run logs, sources, hypotheses.
- **Models:** Gemini 2.5 Flash-Lite for cheap stages, Claude Haiku for synthesis. Selection lives in `config/models.yaml`; no model IDs in code.
- **Delivery:** Telegram Bot API + WhatsApp (second dedicated number). OpenClaw handles both natively.

See `AGENTS.md` for the per-engine reference. See `CLAUDE.md` for the working agreement that governs any AI assistant editing this repo.

## Prerequisites

- Python 3.13+ on Windows (PowerShell is the working shell).
- Supabase project (Postgres + pgvector). Recommended: a project dedicated to NewsFramer.
- API keys: Google AI Studio (Gemini), Anthropic (Claude).
- Telegram bot token + your own chat ID.
- WhatsApp on a dedicated second number (paired to OpenClaw via QR).
- OpenClaw installed and running on the always-on PC.

## Repo layout

```
newsframer/
├── AGENTS.md                       Engine reference
├── CLAUDE.md                       Working agreement for AI assistants
├── README.md                       This file
├── eval_classifier.py              Standalone Classifier inspection script
├── agents/
│   ├── analyst.py
│   ├── classifier.py
│   ├── deduplicator.py
│   ├── fetcher.py
│   └── writer.py
├── config/
│   └── models.yaml                 Model selection, thresholds, pricing, window hours
├── prompts/
│   ├── analyst/system_prompt.txt
│   └── writer/{system_prompt.txt, tone.txt, format_rules.txt}
└── venv/                           Local virtualenv (gitignored)
```

## Configuration

All tuning is outside Python code.

| What | Where |
|------|-------|
| Model selection, thresholds, window hours, pricing | `config/models.yaml` |
| Analyst scoring behavior | `prompts/analyst/system_prompt.txt` |
| Briefing tone | `prompts/writer/tone.txt` |
| Briefing format / character caps / sources style | `prompts/writer/format_rules.txt` |
| Operator interests + hypotheses | `user_context` table (Supabase) |
| RSS sources | `sources` table (Supabase) |
| Junk URL / title filters | `junk_patterns` table (Supabase) |
| Scheduling, Skill wiring, Telegram / WhatsApp delivery | OpenClaw config (out of repo) |

## Secrets

Credentials live in `.env` and are read by every engine via `python-dotenv`.

`.env`, any `*.env`, `*.key`, and `*.pem` files are gitignored. Never commit credentials. Never paste keys into chat with the AI assistant — it does not need to see them.

This repo does not currently ship an `.env.example`. The environment variables the engines read are `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, plus the provider API keys consumed by LiteLLM.

## Running

The settled architecture is for OpenClaw to schedule and run the pipeline as a sequence of Skills. Each engine can also be run manually from PowerShell for testing or recovery:

```powershell
.\venv\Scripts\Activate.ps1
python agents\fetcher.py
python agents\classifier.py
python agents\deduplicator.py            # dry-run by default
python agents\deduplicator.py --apply    # apply dedup mutations
python agents\analyst.py
python agents\writer.py
python eval_classifier.py                # inspection-only, after classifier.py
```

There is no `run_pipeline.py` orchestrator script in the repo at the moment.

## Cost

Designed to run cheap. Cost discipline rules:

- Cheap models for skim / classify / dedup; writer-grade model only for synthesis.
- Opus off by default. Sonnet sparingly.
- USD $2/day is a disaster cap, not a target.

## License / scope

Personal tool. No public guarantees. Treat any code, prompt, or configuration in this repo as evolving; the working agreement (`CLAUDE.md`) is the binding document for collaborators.
