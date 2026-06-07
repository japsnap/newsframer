-- NewsFramer — user_context example/template (PLACEHOLDER DATA ONLY)
--
-- Real interests and hypotheses live in your Supabase project, NOT in this repo.
-- This file is a template so a new operator can see the shape and seed their own.
--
-- NOTE: the column list below is RECONSTRUCTED from what the agents actually read
-- (agents/analyst.py, agents/writer.py: id, topic, stance, reasoning, confidence,
-- specificity, kind, weight, active, status). The authoritative schema lives in
-- Supabase — verify column types/constraints there before relying on this DDL.

create table if not exists user_context (
    id           uuid primary key default gen_random_uuid(),
    kind         text not null check (kind in ('interest', 'hypothesis')),
    topic        text not null,
    stance       text,          -- hypotheses: your directional position
    reasoning    text,          -- hypotheses: why you hold it / what would change it
    confidence   int,           -- hypotheses: 0..10
    specificity  text,          -- e.g. 'specific' | 'broad'
    weight       int,           -- interests: signed relevance nudge (e.g. +3..-3)
    status       text,          -- hypotheses: active | partially_confirmed | pending_confirmation | ...
    active       boolean not null default true,
    created_at   timestamptz not null default now()
);

-- PLACEHOLDER interests (replace with your own; weight is a signed relevance nudge)
insert into user_context (kind, topic, weight, active) values
  ('interest', 'example-interest-topic-a',  2, true),
  ('interest', 'example-interest-topic-b', -1, true);

-- PLACEHOLDER hypotheses (only active/partially_confirmed/pending_confirmation feed the Analyst)
insert into user_context (kind, topic, stance, confidence, reasoning, specificity, status, active) values
  ('hypothesis', 'Example hypothesis: <short testable claim about a domain you track>',
   'neutral', 5, 'Placeholder reasoning — replace with your own.', 'specific', 'active', true),
  ('hypothesis', 'Example hypothesis: <another testable claim>',
   'neutral', 3, 'Placeholder reasoning — replace with your own.', 'broad', 'pending_confirmation', true);
