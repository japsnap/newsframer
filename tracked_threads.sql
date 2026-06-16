-- NF-C1 (spec §4.4 / §9): persistent watchlist of ongoing stories tracked across days for
-- news-context-shift sequencing. Applied to Supabase project aiabggajuzhkfnuaqqre on 2026-06-17
-- via apply_migration (migration: create_tracked_threads_nf_c1). Kept here for reproducibility.
-- Service-role writes only (RLS on, no public policies), matching the other app tables.
create table if not exists public.tracked_threads (
  id            uuid primary key default gen_random_uuid(),
  label         text not null,                       -- short, stable human label ("Gaza casualties")
  delta_type    text,                                -- last detected delta type (1 of the 7), or null
  watchlist     boolean not null default false,      -- true = earns the 30-day lookback (§4.4)
  embedding     vector(768),                         -- representative vector for Stage-0 cross-day match
  cluster_id    uuid,                                -- most-recent dedup cluster_id (the 48h spine)
  points        jsonb not null default '[]'::jsonb,  -- trajectory: [{as_of,value,unit,short_fact,article_ids,delta_type}]
  week_start    date,                                -- JST Monday of the current chain (Monday-reset key, §4.2)
  first_seen_at timestamptz not null default now(),
  last_seen_at  timestamptz not null default now(),
  active        boolean not null default true
);
create index if not exists idx_tracked_threads_active    on public.tracked_threads (active);
create index if not exists idx_tracked_threads_last_seen on public.tracked_threads (last_seen_at);
alter table public.tracked_threads enable row level security;
