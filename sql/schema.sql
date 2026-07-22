-- NewsFramer — complete from-zero database schema.
-- Run this ONCE in the Supabase SQL editor on a fresh project, top to bottom. It creates exactly the
-- tables the pipeline code touches (10). After this, load the seed data:
--   sql/seed_sources.sql, sql/seed_junk_patterns.sql, and (edited) sql/seed_user_context.example.sql.
--
-- Fidelity note: this mirrors the live production schema as of 2026-07-22. A couple of columns carry
-- historical names (e.g. analyst_scores.shota_actual_score, user_context."ai_补完") that the engine
-- code reads by name — they are kept verbatim on purpose so the code runs unchanged.
--
-- All writes are service-role only in production. Row Level Security is left as Supabase defaults
-- except where an original migration explicitly enabled it (tracked_threads), preserved below.

-- pgvector — required for the 768-dim embeddings used by the deduplicator and thread tracker.
create extension if not exists vector;


-- ---------------------------------------------------------------------------
-- sources — RSS / scrape source registry (bundles, region, Ground News tags, per-source window +
-- weekly scrape calendar). Seeded by sql/seed_sources.sql.
-- ---------------------------------------------------------------------------
create table if not exists sources (
  id                          uuid primary key default gen_random_uuid(),
  name                        text,
  url                         text,
  type                        text,
  active                      boolean default true,
  last_fetched                timestamptz,
  avg_relevance_score         double precision default 0,
  articles_fetched            integer default 0,
  articles_used               integer default 0,
  quality_score               double precision default 0,
  category                    text,                                -- topic bundle: crypto/geopolitics/tech/vc/...
  weight                      double precision default 1.0,        -- editorial weight (tune freely)
  source_type                 text,                                -- news/blog/research/vc_blog
  has_rss                     boolean default true,
  rss_url                     text,
  site_url                    text,
  publisher_bias_score        double precision,
  bias_source                 text default 'publisher_average',
  language                    text default 'en',
  notes                       text,
  fetch_mode                  text default 'rss',                  -- rss | browser_required
  fetch_window_hours          integer default 24,                  -- per-source freshness window (§8.1)
  region                      text,
  groundnews_factuality       text,                                -- High | Mixed | Low
  scrape_days                 text,                                -- JST-weekday scrape calendar, e.g. 'wed,sat' (§8.7)
  groundnews_publication_bias text                                 -- left | center | right
);


-- ---------------------------------------------------------------------------
-- raw_articles — every fetched article; soft-deleted (never hard-deleted). Carries the embedding and
-- the dedup cluster wiring.
-- ---------------------------------------------------------------------------
create table if not exists raw_articles (
  id              uuid primary key default gen_random_uuid(),
  source_id       uuid,
  title           text,
  -- The live DB dedups URLs in code and has NO unique constraint on url. For a fresh install we ADD
  -- `unique` here so accidental duplicate inserts are rejected at the DB layer; the code is compatible
  -- (it already avoids re-inserting a URL it has seen). Live-DB divergence is intentional — flagged.
  url             text unique,
  content_raw     text,
  published_at    timestamptz,
  branch          text,                                    -- IMMEDIATE | KEEP_WARM (classifier)
  days_tracked    integer default 0,
  was_published   boolean default false,
  keep_warm_score double precision,
  duplicate_count integer default 1,
  created_at      timestamptz default now(),
  deleted_at      timestamptz,                             -- soft-delete stamp
  deleted_by      text,
  deletion_reason text,
  embedding       vector(768),
  duplicate_of    uuid,
  cluster_id      uuid
);
create index if not exists idx_raw_articles_cluster
  on raw_articles (cluster_id) where cluster_id is not null;
create index if not exists idx_raw_articles_embedding
  on raw_articles using hnsw (embedding vector_cosine_ops);


-- ---------------------------------------------------------------------------
-- analyst_scores — per-article relevance + hypothesis alignment. Idempotent via UNIQUE(article_id).
-- ---------------------------------------------------------------------------
create table if not exists analyst_scores (
  id                    uuid primary key default gen_random_uuid(),
  article_id            uuid unique,                       -- one score row per article (idempotency key)
  relevance_score       integer,                           -- 0..10 signal/noise gate
  hypothesis_alignment  integer,                           -- deprecated per spec §15; kept for schema fidelity
  label                 text,                              -- CONFIRMS_/CHALLENGES_HYPOTHESIS | NEW_SIGNAL | NEUTRAL
  sentiment             text,
  model_used            text,
  analyst_predicted_score integer,
  shota_actual_score    integer,                           -- historical column name; read by code as-is
  prediction_error      double precision,
  created_at            timestamptz default now(),
  reasoning             text,
  topics                text[],
  actionability         smallint,
  perspective_invited   boolean default false,
  stale_after_hours     integer,
  hypotheses            jsonb,
  differentiator        text
);
create index if not exists idx_analyst_scores_hypotheses on analyst_scores using gin (hypotheses);


-- ---------------------------------------------------------------------------
-- briefings — the synthesized daily brief (multi-language bodies + dispatch bookkeeping).
-- ---------------------------------------------------------------------------
create table if not exists briefings (
  id                     uuid primary key default gen_random_uuid(),
  date                   date,
  content_ja             text,
  content_en             text,
  content_ur             text,
  model_writer           text,
  prompt_version         text,
  cost_usd               double precision,
  created_at             timestamptz default now(),
  overall_rating         integer,
  overall_notes          text,
  what_missed            text,
  agent_readable_summary text,
  dispatched_at          timestamptz,
  dispatch_target        text,
  dispatch_message_ids   integer[],
  article_ids            jsonb
);


-- ---------------------------------------------------------------------------
-- deliveries — the confirmed-send ledger (§4.3). An article is recorded here per account ONLY after a
-- real messageId came back. UNIQUE(article_id, account) makes recording idempotent.
-- ---------------------------------------------------------------------------
create table if not exists deliveries (
  id           uuid primary key default gen_random_uuid(),
  article_id   uuid not null,
  account      text not null,                              -- 'newsframer' (Telegram) | 'whatsapp:<name>'
  brief_id     uuid,
  delivered_at timestamptz not null default now(),
  unique (article_id, account)
);
create index if not exists idx_deliveries_account on deliveries (account);


-- ---------------------------------------------------------------------------
-- junk_patterns — URL / title filters applied at fetch. Seeded by sql/seed_junk_patterns.sql.
-- ---------------------------------------------------------------------------
create table if not exists junk_patterns (
  id                 uuid primary key default gen_random_uuid(),
  pattern            text,
  pattern_type       text,                                 -- url_contains | url_endswith | title_contains
  source_of_pattern  text default 'janitor',
  confidence         integer default 5,
  approved_by_shota  boolean default false,                -- historical column name; kept for fidelity
  times_used         integer default 0,
  active             boolean default true,
  added_at           timestamptz default now()
);


-- ---------------------------------------------------------------------------
-- user_context — operator interests + tracked hypotheses that the Analyst scores against. Seed with
-- sql/seed_user_context.example.sql (edited to your own interests). Runs cleanly with zero rows.
-- ---------------------------------------------------------------------------
create table if not exists user_context (
  id                   uuid primary key default gen_random_uuid(),
  topic                text,
  stance               text,
  reasoning            text,
  confidence           integer,
  specificity          text,
  "ai_补完"            text,                                -- legacy CJK column name; kept, code-compatible
  shota_confirmed      boolean default false,
  status               text default 'pending_confirmation',
  outcome_notes        text,
  outcome_date         timestamptz,
  active               boolean default false,
  source               text,
  updated_at           timestamptz default now(),
  notes                text,
  notify_to_clarify    boolean default true,
  clarification_sent_at timestamptz,
  tags                 text[],
  kind                 text not null default 'hypothesis',  -- 'interest' | 'hypothesis'
  weight               integer
);
create index if not exists idx_user_context_active
  on user_context (active, status) where active = true;


-- ---------------------------------------------------------------------------
-- agent_runs — one row per engine run (cost, duration, model, status). Best-effort logging.
-- ---------------------------------------------------------------------------
create table if not exists agent_runs (
  id          uuid primary key default gen_random_uuid(),
  agent_name  text,
  model_used  text,
  tokens_in   integer,
  tokens_out  integer,
  cost_usd    double precision,
  duration_ms integer,
  status      text,                                        -- success | partial | failed
  error       text,
  day_of_week smallint,
  local_hour  smallint,
  created_at  timestamptz default now()
);


-- ---------------------------------------------------------------------------
-- execution_log — per-run observability + cost trace (spec §9). All engines of one run share a
-- trace_id (NEWSFRAMER_TRACE_ID). Written best-effort by agents/run_log.record_run.
-- ---------------------------------------------------------------------------
create table if not exists execution_log (
  id                bigint generated by default as identity primary key,
  trace_id          text not null,
  created_at        timestamptz not null default now(),
  project           text default 'newsframer',
  task_type         text,                                  -- 'brief' | 'whatsapp_brief' | ...
  agent             text,                                  -- engine name
  model_used        text,
  actual_cost       numeric default 0,
  tokens_in         integer default 0,
  tokens_out        integer default 0,
  status            text,                                  -- success | partial | failed
  error_trace       text,
  linked_hypotheses jsonb,
  artifact_verified boolean default false
);
create index if not exists execution_log_trace_idx   on execution_log (trace_id);
create index if not exists execution_log_created_idx on execution_log (created_at desc);


-- ---------------------------------------------------------------------------
-- tracked_threads — persistent watchlist of ongoing stories tracked across days (spec §4.4).
-- Service-role writes only (RLS on, no public policies).
-- ---------------------------------------------------------------------------
create table if not exists public.tracked_threads (
  id            uuid primary key default gen_random_uuid(),
  label         text not null,                             -- short stable human label ("Gaza casualties")
  delta_type    text,
  watchlist     boolean not null default false,            -- true = earns the 30-day lookback (§4.4)
  embedding     vector(768),
  cluster_id    uuid,
  points        jsonb not null default '[]'::jsonb,        -- trajectory points
  week_start    date,                                      -- JST Monday of the current chain (§4.2)
  first_seen_at timestamptz not null default now(),
  last_seen_at  timestamptz not null default now(),
  active        boolean not null default true
);
create index if not exists idx_tracked_threads_active    on public.tracked_threads (active);
create index if not exists idx_tracked_threads_last_seen on public.tracked_threads (last_seen_at);
alter table public.tracked_threads enable row level security;
