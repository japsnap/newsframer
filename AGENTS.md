# OpenClaw

## What this is
Shota's personal AI agent system. Runs daily crypto/tech/geopolitical 
news briefings, learns from feedback, and grows over time.

## Architecture
- Framework: CrewAI OSS + LiteLLM
- Pattern: Choreography (event-driven, no central orchestrator)
- State: Supabase
- Delivery: Telegram Bot
- Hosting: Google Cloud Run

## Agents and their roles
- Fetcher: collects articles from RSS and web sources
- Classifier: decides Branch A (immediate) or Branch B (keep warm)
- Analyst: scores relevance and alignment with Shota's hypotheses (Claude Haiku)
- Writer: generates briefings in Japanese, English, Urdu (Claude Sonnet)
- Dispatcher: sends output to Telegram, saves drafts to Supabase

## Shota's current hypotheses (update regularly)
- XRP: bearish at current price range
- ETH: bullish, watching L2 TVL growth
- General: real adoption > speculation

## Rules
- Never hardcode API keys — always use .env
- Always log agent runs to Supabase agent_runs table
- models.yaml controls all model selection — never hardcode model names
- Keep feedback data — it makes the system smarter over time

## Security rules
- .env is gitignored — never commit API keys
- Never print API keys in logs
- Supabase service role key is server-side only, never in client code
- agent_runs table logs errors without exposing key values
- If adding new API keys, add to .env AND .gitignore first