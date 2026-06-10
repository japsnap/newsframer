# NewsFramer — Engine Reference

## What this is

A personal news automation pipeline. Pulls articles from RSS sources, classifies them, deduplicates them, scores them against the operator's interests and tracked hypotheses, synthesizes a themed briefing, and delivers it to Telegram and WhatsApp on a daily schedule. Personal use; low cost.

## Architecture (settled)

- **Conductor / runtime:** **OpenClaw** (`openclaw.ai`) running on an always-on PC. OpenClaw schedules pipeline runs (cron + weekly Monday hard reset), invokes each engine as a Skill, and delivers the brief to Telegram and WhatsApp directly. There is no separate dispatch layer.
- **Stack:** Python 3.13 · Supabase (Postgres + pgvector) · LiteLLM · Telegram Bot API · WhatsApp (second number).
- **Pattern:** Sequential pipeline of five engines. Each engine is a standalone Python module under `agents/`, wrapped as an OpenClaw Skill. No engine calls another engine in code — Supabase carries state between them, so every engine is re-runnable in isolation.
- **Scraping:** Custom Python Fetcher (RSS) is primary. For JS-heavy / bot-protected / non-RSS sources, the fallback is the OpenClaw **browser / Firecrawl** skill. Dedup at the URL layer happens **before** the scrape so fallback never re-fetches what RSS already returned.
- **Models:** All model choices live in `config/models.yaml`. Never hardcode model IDs in engine code.
- **Prompts:** `prompts/<engine>/*.txt` — edit without touching code.

CrewAI is not used.

## Engines (5)

### Fetcher — `agents/fetcher.py`
Pulls articles from RSS sources configured in the `sources` table. Two passes: priority "thinker" sources first (guaranteed), then news sources up to the configured total. Junk filtered via `junk_patterns`. URL dedup at insert.
- **Model:** none (RSS only).
- **Fallback for non-RSS / JS-heavy sources:** OpenClaw browser / Firecrawl skill. Must be dedup-guarded — never re-scrape what RSS already returned (spec §3.3).
- **Per-source fetch window** (`fetch_window_hours`, spec §8.1) and a **distributed weekly scrape calendar** (`scrape_days`, keyed to the JST weekday, spec §8.7) are honored — so low-frequency sources are not missed and heavy scrape jobs are spread across the week. Sources also carry `region` + Ground News bias/factuality tags (§8.2); bundles live in the `category` column.

### Classifier — `agents/classifier.py`
Labels each unclassified article as `IMMEDIATE` (time-sensitive: price moves, breaking news, regulatory, geopolitics, confirmed launches) or `KEEP_WARM` (analytical / slower / hypothesis-related). Batches per LLM call. Detects intra-batch topic duplicates.
- **Model:** per `classifier_model` in `config/models.yaml`.

### Deduplicator — `agents/deduplicator.py`
Generates 768-dim embeddings, finds candidate pairs within the configured window by cosine similarity, clusters them via union-find, and resolves each cluster:
- `price_event` (cluster spans the short window AND a member title/topic carries price/event keywords) → keep latest.
- `analysis` (everything else) → keep earliest (originator). Low-confidence analysis clusters are flagged for review, not deleted.

Default is dry-run; `--apply` mutates.

- **Model:** embedding model per `deduplicator_embedding_model` in `config/models.yaml`.

### Analyst — `agents/analyst.py`
Per-article reasoning. For each classified, non-deleted article not yet scored:
- `relevance_score` 0–10 against active interests and hypotheses loaded from `user_context`.
- Label: `CONFIRMS_HYPOTHESIS` / `CHALLENGES_HYPOTHESIS` / `NEW_SIGNAL` / `NEUTRAL`. Surfaces contradicting evidence; does not filter it.
- Per-hypothesis alignment (`-2..+2`), topics, actionability, perspective flag, reasoning.

Idempotent via `UNIQUE(article_id)` in the scores table. Runs cleanly with zero hypotheses. Prompt: `prompts/analyst/system_prompt.txt`.
- **Model:** per `analyst_model` in `config/models.yaml`.

### Writer — `agents/writer.py`
Loads top-scoring articles within the freshness window, groups them into themes, and synthesizes a fact-organized briefing (themed sections + highlights) into the `briefings` table. Prompt is split across `prompts/writer/{system_prompt,tone,format_rules}.txt` so tone / format can be tuned without touching code.
- **Model:** per `writer_model` in `config/models.yaml`.
- Briefing date/header is computed in **JST** (Asia/Tokyo), not UTC. The character cap **scales with theme count** (`writer_per_theme_chars` × themes, clamped to floor..ceiling). On an Anthropic outage / rate-limit / billing error the writer **falls back to `writer_fallback_model`** (Gemini Flash-Lite); the `newsframer` OpenClaw agent has the same fallback.

## Delivery — OpenClaw

OpenClaw delivers natively to both **Telegram (operator)** and **WhatsApp (second number)** — including group + DM splitting and broadcast. There is no custom Dispatcher in the settled architecture. The legacy `agents/dispatcher.py` is on the deletion list and remains in the repo only until OpenClaw delivery is wired; it is not part of the target pipeline.

### Daily schedule (OpenClaw gateway crons)

Two persistent gateway crons run on the always-on PC's background scheduled task (survives logout / reboot):

- **`newsframer-daily`** — 06:00 JST. Runs `run_brief.py` (the 5 engines, no Dispatcher) and delivers the full brief to the operator's **Telegram**.
- **`newsframer-whatsapp-daily`** — 11:00 JST. Runs `run_whatsapp_brief.py --send` to post per-chat **WhatsApp** briefs, then announces a one-line status to Telegram.

### WhatsApp briefs — `run_whatsapp_brief.py`

Separate from the Telegram brief. Reuses the Writer's functions (writer.py untouched), passes empty user-context (no private hypotheses reach external chats), and does **not** write to `briefings`. Driven by a gitignored per-chat registry `config/whatsapp_deliveries.yaml` (template: `config/whatsapp_deliveries.example.yaml`):

- **Topic-based selection** — articles are chosen by their analyst `topics`, not their source, per the chat's `categories` (so an off-topic story from an on-topic source is dropped).
- **Per-chat languages** — `languages[0]` is primary and carries the sources/links; later languages translate from a source-stripped copy (one source list per chat).
- **Targets** — a group (saved JID) or a DM (E.164 number); sent via `openclaw message send`. Group JIDs are captured once, then saved in the registry.

## Key rules

- **Never hardcode API keys.** Everything secret routes through `.env`. `.env`, `.key`, `.pem` are gitignored.
- **Never hardcode model IDs in engine code.** Read from `config/models.yaml`.
- **Log every engine run** to `agent_runs` (cost, duration, model, status).
- **Soft-delete only** — never hard-delete articles. The audit trail matters for the future feedback / review loop.
- **All numeric thresholds** (windows, score floors, batch sizes, character caps) live in `config/models.yaml`, not in code.
- **Cost discipline:** cheap model for skim / classify stages; writer-grade model only for real synthesis. **Opus off by default. Sonnet sparingly.** The daily disaster cap is USD $2/day; this is not a target, it is a kill-switch.
- **Anti-hallucination — data-to-data only.** "What changed since last delivery" is computed from source articles in the DB, never by summarizing a previously *written* briefing. Writer only ever summarizes article content with citations.
- **Verify real artifacts, never trust return values.** "Delivered" = the message was sent to Telegram / WhatsApp, not "the function returned."

## Configuration

| What | Where |
|------|-------|
| Model selection, thresholds, window hours, pricing | `config/models.yaml` |
| Analyst scoring behavior | `prompts/analyst/system_prompt.txt` |
| Briefing tone | `prompts/writer/tone.txt` |
| Briefing format / character caps / sources style | `prompts/writer/format_rules.txt` |
| Operator interests + hypotheses | `user_context` table (Supabase) |
| RSS sources, bundles, region/Ground News tags, per-source window + scrape calendar | `sources` table (Supabase) |
| WhatsApp per-chat delivery registry (group JIDs + DM numbers) — **gitignored** | `config/whatsapp_deliveries.yaml` (template `*.example.yaml`) |
| Junk filters | `junk_patterns` table (Supabase) |
| Scheduling, Skill wiring, Telegram / WhatsApp delivery | OpenClaw config (out of repo) |

## Inspection

- `eval_classifier.py` — standalone inspection script. Reports branch distribution, intra-batch dedup hits, samples of `IMMEDIATE` / `KEEP_WARM` classifications, and any junk URLs that slipped through. Run after `classifier.py` to sanity-check its decisions. No parallel inspection script exists for the other engines yet.

## Operator notes

- `CLAUDE.md` (in the repo root) is the working agreement for any AI assistant editing this codebase. Read it before changing anything.
- The detailed product spec is maintained outside this repo and is the source of truth for design decisions. On any contradiction between code/docs and spec, stop and ask — never resolve silently.
