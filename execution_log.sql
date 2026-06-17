-- NF-14 / spec §9 — execution_log: per-pipeline-run observability + cost trace.
-- Applied to Supabase project aiabggajuzhkfnuaqqre via apply_migration (create_execution_log_nf14),
-- 2026-06-18. Kept here for reproducibility (mirrors the tracked_threads.sql convention).
--
-- One row per engine per run; all engines of a run share a `trace_id` (minted by run_brief.py and
-- passed via NEWSFRAMER_TRACE_ID). Written best-effort by agents/run_log.record_run — NEVER in the
-- critical path, so a missing table / failed insert can't affect agent_runs or the brief.
create table if not exists execution_log (
  id                bigint generated always as identity primary key,  -- job_id
  trace_id          text not null,                                    -- ties one run's engines together
  created_at        timestamptz not null default now(),
  project           text default 'newsframer',
  task_type         text,                                             -- 'brief' | 'whatsapp_brief' | ...
  agent             text,                                             -- engine: fetcher/classifier/.../writer
  model_used        text,
  actual_cost       numeric default 0,
  tokens_in         integer default 0,
  tokens_out        integer default 0,
  status            text,                                             -- success | partial | failed
  error_trace       text,
  linked_hypotheses jsonb,                                            -- populated by the Analyst (follow-up)
  artifact_verified boolean default false                             -- true only when a real artifact exists
);
create index if not exists execution_log_trace_idx on execution_log (trace_id);
create index if not exists execution_log_created_idx on execution_log (created_at desc);
