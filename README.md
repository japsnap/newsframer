# NewsFramer

A personal news automation pipeline that delivers daily briefings to Telegram.

## What it does

Fetches articles from your configured RSS sources, classifies and deduplicates them, scores against your interests and hypotheses, synthesizes into themed sections, and delivers to your Telegram every morning.

Daily cost: ~$0.04

## Prerequisites

- Python 3.13+
- Supabase account (free tier sufficient) — separate project recommended, not shared with other apps
- Google AI Studio API key (Gemini 2.5 Flash-Lite)
- Anthropic API key (Claude Haiku)
- Telegram bot token + your chat ID

## Setup

1. Clone the repo
2. Create and activate venv:
   ```
   python -m venv venv
   .\venv\Scripts\activate   # Windows
   source venv/bin/activate  # Mac/Linux
   ```
3. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
4. Copy `.env.example` to `.env` and fill in your credentials
5. Run schema migrations in your Supabase SQL editor (see `migrations/`)
6. Seed your interests:
   ```sql
   INSERT INTO user_context (topic, kind, weight, active, source)
   VALUES ('crypto markets', 'interest', 3, true, 'baseline');
   ```
7. Seed your RSS sources:
   ```sql
   INSERT INTO sources (name, url, category, active)
   VALUES ('CoinDesk', 'https://www.coindesk.com/arc/outboundfeeds/rss/', 'crypto_news', true);
   ```

## Run manually

```
python run_pipeline.py
```

## Configuration

All tuning is done outside Python code:

| What | Where |
|------|-------|
| Model choices, thresholds, window hours | `config/models.yaml` |
| Analyst scoring behavior | `prompts/analyst/system_prompt.txt` |
| Briefing tone | `prompts/writer/tone.txt` |
| Briefing format | `prompts/writer/format_rules.txt` |
| Your interests and hypotheses | `user_context` table in Supabase |
| RSS sources | `sources` table in Supabase |
| Junk filters | `junk_patterns` table in Supabase |

## Architecture

6 agents run sequentially via `run_pipeline.py`:

| Agent | What it does | Cost/run |
|-------|-------------|----------|
| Fetcher | Pulls articles from RSS sources | ~$0 |
| Classifier | Labels each article IMMEDIATE or KEEP_WARM | ~$0.005 |
| Deduplicator | Clusters and soft-deletes duplicate articles | ~$0.001 |
| Analyst | Scores each article 0-10 against your interests | ~$0.015 |
| Writer | Synthesizes top articles into a themed briefing | ~$0.02 |
| Dispatcher | Sends briefing to Telegram | ~$0 |

The database (Supabase) is the orchestration layer. Each agent reads and writes SQL tables independently. No agent calls another agent directly — this makes every agent re-runnable in isolation.

## Adding hypotheses

Beyond interests, you can track specific beliefs and let the Analyst surface confirming or challenging evidence:

```sql
INSERT INTO user_context (topic, kind, stance, weight, active, source)
VALUES (
  'stablecoin regulation',
  'hypothesis',
  'US stablecoin bill will pass by Q3 2026',
  2,
  true,
  'manual'
);
```

The Analyst will label relevant articles as CONFIRMS_HYPOTHESIS or CHALLENGES_HYPOTHESIS.

## Deployment

For automated daily runs, deploy to Google Cloud Run with Cloud Scheduler set to your preferred time. See `Dockerfile` for container setup.
