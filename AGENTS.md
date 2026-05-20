# NewsFramer — Agent Reference

## What this is

A personal news automation pipeline. Runs daily, delivers a themed briefing to Telegram.

## Architecture

- **Stack:** Python 3.13, Supabase (Postgres + pgvector), LiteLLM, Telegram Bot API
- **Pattern:** Sequential pipeline. Each agent is a standalone script. No agent calls another agent.
- **Orchestration:** Database. Agents read/write Supabase tables and exit. `run_pipeline.py` runs all 6 in sequence.
- **Hosting:** Google Cloud Run + Cloud Scheduler (daily at 06:00 JST)
- **Models:** `config/models.yaml` controls all model selection — never hardcoded in agent code
- **Prompts:** `prompts/<agent>/*.txt` — edit without touching code

---

## Agents

### Fetcher (`agents/fetcher.py`)
Pulls articles from RSS sources configured in the `sources` table. Two passes: priority thinker sources first, then news sources. Filters junk via `junk_patterns` table. Soft-deduplicates by URL.
- **Model:** None (RSS only)
- **Cost:** ~$0

### Classifier (`agents/classifier.py`)
Labels each unclassified article as `IMMEDIATE` (time-sensitive) or `KEEP_WARM` (analytical). Batches 10 articles per LLM call. Detects intra-batch duplicates.
- **Model:** `gemini/gemini-2.5-flash-lite`
- **Cost:** ~$0.005

### Deduplicator (`agents/deduplicator.py`)
Generates 768-dim embeddings, finds similar article pairs (cosine ≥ 0.85), clusters them, soft-deletes losers. Two cluster types: `price_event` (keep latest) and `analysis` (keep earliest/originator). Run with `--apply` to mutate; default is dry-run.
- **Model:** `gemini/gemini-embedding-001`
- **Cost:** ~$0.001

### Analyst (`agents/analyst.py`)
Scores each article 0-10 against user interests and active hypotheses loaded from `user_context` table. Labels each as `CONFIRMS_HYPOTHESIS`, `CHALLENGES_HYPOTHESIS`, `NEW_SIGNAL`, or `NEUTRAL`. Does not filter contradicting content — surfaces it. Prompt lives in `prompts/analyst/system_prompt.txt`.
- **Model:** `gemini/gemini-2.5-flash-lite`
- **Cost:** ~$0.015

### Writer (`agents/writer.py`)
Loads top-scoring articles, clusters by topic overlap, synthesizes 3-5 themed sections + 8 highlights into a Markdown briefing. Stores in `briefings` table. Prompt split across `prompts/writer/system_prompt.txt`, `tone.txt`, `format_rules.txt`.
- **Model:** `anthropic/claude-haiku-4-5`
- **Cost:** ~$0.02

### Dispatcher (`agents/dispatcher.py`)
Loads the latest un-dispatched briefing, splits at `##` section boundaries if over the char limit, sends to Telegram. Marks briefing as dispatched with message IDs.
- **Model:** None
- **Cost:** ~$0

---

## Key rules

- Never hardcode API keys — always use `.env`
- Never hardcode model names in code — always read from `config/models.yaml`
- Always log agent runs to `agent_runs` table (cost, duration, model, status)
- Soft-delete only — never hard-delete articles (audit trail for future Coach agent)
- All numeric thresholds live in `config/models.yaml`, not in code

---

## Configuration

| What | Where |
|------|-------|
| Model selection, thresholds, window hours | `config/models.yaml` |
| Analyst scoring behavior | `prompts/analyst/system_prompt.txt` |
| Briefing tone | `prompts/writer/tone.txt` |
| Briefing format | `prompts/writer/format_rules.txt` |
| User interests and hypotheses | `user_context` table (Supabase) |
| RSS sources | `sources` table (Supabase) |
| Junk filters | `junk_patterns` table (Supabase) |

---

## Roadmap

### Phase 1.5 (next)
- Critic agent — pre-send quality check (broken markdown, char overruns, editorial drift)
- Telegram feedback loop — rate articles, system adjusts interest weights

### Phase 2
- Drafter agent — post drafts for X/Threads/Instagram/TikTok in user's voice
- Coach agent — Telegram-driven calibration (`/more crypto`, `/less geopolitics`)
- CrewAI integration — inter-agent dialogue for Drafter/Coach patterns
