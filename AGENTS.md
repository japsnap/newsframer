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
- **Per-bundle theme floors (§8.1/§8.6):** after the unchanged clustering, theme slots are re-allocated so every active bundle (source `category`) with a qualifying article gets at least its floor of themes, no bundle exceeds its cap, and the total scales with the active-bundle count (`bundle_theme_floors`, `bundle_theme_cap`, `theme_count_multiplier`, `theme_count_max`). A bundle with nothing qualifying is simply absent — no stale padding.
- **Drop-reports (§8.5):** investigative-category articles are pulled out of the normal pool and handled on a wider 7-day deduped window, rendered as a distinct `## 🔍 Investigations` section (woven into the main theme when topics match), with a short + long pair stored locally; `get_drop_report.py` returns the long form on a "more: <slug>" reply. Telegram-self path only.
- Theme and highlight titles are **Title Case** (acronyms/tickers preserved); the exact theme/highlight counts and character limit are injected from config, not baked into the prompt.

## Supporting modules

Not engines, but shared infrastructure the pipeline depends on:
- `agents/llm_json.py` — tolerant parsing of LLM JSON (object/array/string/null, markdown fences, surrounding prose) so a shape slip degrades to "skip this item" instead of crashing a stage.
- `agents/run_log.py` — `record_run()` writes each engine's `agent_runs` row best-effort, so a bookkeeping blip can't sink an otherwise-good run.
- `agents/bundle_floors.py` — the per-bundle theme allocation (floors + caps), pure logic.
- `agents/drop_reports.py` — the investigative drop-report logic (slug, weave detection, the Investigations section), pure logic.
- `agents/deliver.py` — the **confirmed-send delivery seam**: send via the gateway subprocess and record a brief's article IDs **only after every chunk returns a real messageId**; on failure, record nothing and alert.

## Delivery — OpenClaw

OpenClaw delivers to both **Telegram (operator)** and **WhatsApp (second number)** through its gateway `message send` (which returns a real messageId). The legacy `agents/dispatcher.py` is **superseded** by this path and kept only for reference.

**§4.3 confirmed-send recording:** a brief's article IDs are recorded as delivered **only after a confirmed send**, never at brief-emit. `deliver_brief.py` (Telegram) and `run_whatsapp_brief.py` (per-chat) send via the gateway subprocess and call the deliveries recording only once every chunk/message returns a messageId; on any failure they record nothing and fire a direct Telegram alert. So the writer's set-difference ("what's new") can never include something that wasn't actually sent.

### Daily schedule (OpenClaw gateway crons)

Persistent gateway crons run on the always-on PC's background scheduled task (survive logout / reboot):

- **`newsframer-daily`** — 06:00 JST. `run_brief.py` (the 5 engines) builds the brief into Supabase, then `deliver_brief.py` sends it to **Telegram** and records §4.3 deliveries on confirmed send.
- **`newsframer-whatsapp-daily`** — 11:00 JST. `run_whatsapp_brief.py --send` posts per-chat **WhatsApp** briefs and records per-chat deliveries on confirmed send.
- **`newsframer-watchdog-telegram`** — 06:30 JST. `check_run_health.py` reads the run's artifacts and alerts the operator (direct Telegram Bot API, independent of OpenClaw delivery) if a stage went partial/failed, no fresh brief was produced, or the run didn't fire (§4.5).

### WhatsApp briefs — `run_whatsapp_brief.py`

Separate from the Telegram brief. Reuses the Writer's functions (writer.py untouched), passes empty user-context (no private hypotheses reach external chats), and does **not** write to `briefings`. Driven by a gitignored per-chat registry `config/whatsapp_deliveries.yaml` (template: `config/whatsapp_deliveries.example.yaml`):

- **Topic-based selection** — articles are chosen by their analyst `topics`, not their source, per the chat's `categories` (so an off-topic story from an on-topic source is dropped).
- **Per-chat languages** — `languages[0]` is primary and carries the sources/links; later languages translate from a source-stripped copy (one source list per chat).
- **Targets** — a group (saved JID) or a DM (E.164 number); sent via `openclaw message send`. Group JIDs are captured once, then saved in the registry.
- **§4.3 recording** — after a chat's sends all confirm a messageId, its article IDs are recorded delivered under `account=whatsapp:<name>` (no `briefings` row is written, so `print_latest_brief`'s "latest brief" stays the Telegram one). A failed send records nothing and alerts.

## Key rules

- **Never hardcode API keys.** Everything secret routes through `.env`. `.env`, `.key`, `.pem` are gitignored.
- **Never hardcode model IDs in engine code.** Read from `config/models.yaml`.
- **Log every engine run** to `agent_runs` (cost, duration, model, status).
- **Soft-delete only** — never hard-delete articles. The audit trail matters for the future feedback / review loop.
- **Nothing operational is hardcoded.** Every tunable (windows, score floors, batch sizes, character/length limits, theme & highlight counts, LLM temperature/max-tokens, retries, message limits, …) lives in `config/models.yaml` and is read with `config.get(key, <default>)`. Prompt files describe behavior; the numbers are injected from config. (See the `CLAUDE.md` hard rule.)
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
