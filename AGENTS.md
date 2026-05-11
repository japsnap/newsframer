# OpenClaw

## What this is
Shota's personal AI agent system. Runs daily crypto/tech/geopolitical
news briefings, learns from feedback, and grows over time.

## Architecture
- Framework: CrewAI OSS + LiteLLM
- Pattern: Choreography (event-driven, no central orchestrator)
- State: Supabase (dedicated openclaw project)
- Delivery: Telegram Bot
- Hosting: Google Cloud Run (always-on) + local PC (for future resource-heavy tasks)
- Models: config/models.yaml controls all model selection

## Agents and their roles
- Fetcher: collects articles from RSS and web sources; uses LLM conditionally for unstructured sources
- Enricher: adds retroactive context to articles (historical prices, chart data, past news) before passing to Analyst; no fixed time range — context depth depends on the topic
- Classifier: assigns Branch A (immediate) or Branch B (keep warm) based on time-sensitivity
- Analyst: scores relevance and hypothesis alignment (Claude Haiku); labels each article as CONFIRMS_HYPOTHESIS / CHALLENGES_HYPOTHESIS / NEW_SIGNAL / NEUTRAL; does not filter out contradicting content — challenges and new signals are shown to Shota
- Writer: generates briefings in Japanese, English, Urdu (Claude Sonnet); covers crypto, AI, tech, and geopolitics daily regardless of hypothesis relevance
- Dispatcher: sends output to Telegram, saves drafts to Supabase
- Tuner: updates prompt few-shots based on high-rated briefings; runs monthly by default, triggerable manually via /tune

## Two-branch pipeline
- Branch A (immediate): breaking price movements, regulatory news, geopolitical events — published same day
- Branch B (keep warm): AI trends, market structure, hypothesis testing — Analyst tracks for multiple days before Writer generates output; weekly deep report

## Feedback system
- Telegram: daily quick feedback via buttons and natural language replies
- Vercel dashboard: weekly detailed review with multi-dimension scoring
- Obsidian journal: nightly MCP sync to user_context table in Supabase
- /tune command: triggers prompt update (default monthly, manual anytime)
- Implicit feedback: Telegram link taps tracked as interest signal; articles ignored for 72+ hours marked as skipped (extended automatically over weekends)

## Hypothesis rules
- Hypotheses live in user_context table in Supabase
- Vague hypotheses: recorded, not validated, not AI-completed; Shota notified once to clarify, reminded once after 2 weeks; can stay vague indefinitely
- Somehow_clear hypotheses: AI may suggest completion; Shota must confirm before activating; no validation runs until confirmed
- Precise hypotheses: full criteria met (condition, timeframe, threshold); goes straight to validation flow
- AI determines specificity from Shota's natural language input; Shota can override
- Validation runs daily or weekly depending on hypothesis type; outcome updates gradually (unconfirmed → partially_confirmed → confirmed / failed)
- Contradicting hypotheses are detected automatically and flagged to Shota via Telegram

## Specificity rules for hypotheses
- vague: notify Shota to clarify, no validation, stays vague if needed
- somehow_clear: AI-assisted completion, Shota confirms before activating
- precise: full criteria met, goes straight to validation flow
- AI determines specificity from Shota's input, Shota can override

## Source quality
- Each source tracks avg_relevance_score, articles_fetched, articles_used, quality_score
- Sources with repeated fetch errors are automatically blacklisted via error_patterns table
- Duplicate articles across sources treated as importance signal — higher duplicate count raises relevance score

## Rules
- Never hardcode API keys — always use .env
- Always log agent runs to Supabase agent_runs table with cost, duration, model used
- models.yaml controls all model selection — never hardcode model names in code
- Keep all feedback data — it makes the system smarter over time
- Prompt versions are tracked in prompt_versions table; never overwrite without logging

## Security rules
- .env is gitignored — never commit API keys
- Never print API keys in logs or error messages
- Supabase service role key is server-side only, never in client code
- agent_runs table logs errors without exposing key values
- If adding new API keys, add to .env AND .gitignore first
- All Telegram interactions use natural language or buttons — no IDs or internal values exposed to Shota

## UX Rules (Telegram)
- All user input must be natural language or button taps
- Never ask for IDs, formatted commands, or anything requiring lookup
- Syntax-based commands are acceptable only where no natural alternative exists
- Always confirm before finalizing any update
- Offer undo or correction at every step