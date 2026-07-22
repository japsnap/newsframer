-- ARCHIVED 2026-07-22 — one-off DATA migration, CONFIRMED applied to the live DB.
-- Verified read-only 2026-07-22: the live DB has category='vc' on the 6 VC sources. Not needed on a
-- fresh install: sql/seed_sources.sql ships all 6 with category='vc' already. Kept for provenance only.
--
-- NF-A1 — split VC into its own bundle (spec §8.6)
-- Run this in the Supabase SQL editor (project: "openclaw" / aiabggajuzhkfnuaqqre) when you're home.
-- Claude Code does NOT run this — you apply it after a glance at step 1.
--
-- What it does: moves all 6 vc_blog sources out of their current bundle (tech / crypto)
-- into a new category='vc'. The repo config is already set up for this — config/models.yaml
-- has `vc: 1` in bundle_theme_floors, so the moment these rows become category='vc',
-- VC gets its own guaranteed theme slot in the Telegram brief (when it has qualifying news).
--
-- Confirmed scope (Shota, 2026-06-13): ALL vc_blog sources go to 'vc' — the 4 tech ones
-- (Andreessen Horowitz, Sequoia Capital, Y Combinator Blog, First Round Review) AND the
-- 2 crypto ones (a16z crypto, Electric Capital).

-- 1) PREVIEW — run this first. Expect exactly 6 rows (4 from tech, 2 from crypto).
select id, name, category, source_type
from sources
where source_type = 'vc_blog'
order by category, name;

-- 2) APPLY — reclassify all vc_blog sources into the 'vc' bundle. Idempotent (safe to re-run).
update sources
set category = 'vc'
where source_type = 'vc_blog';

-- 3) VERIFY — expect 6 rows, all category = 'vc'.
select category, source_type, count(*) as n
from sources
where source_type = 'vc_blog'
group by category, source_type;

-- ---------------------------------------------------------------------------
-- NOTE on the spec §8.6 "VC = Wednesday + Saturday AM" cadence — NOT set here, on purpose.
-- The scrape_days weekday gate (fetcher.py) only applies to SCRAPE sources (no RSS). The VC
-- blogs all have working RSS feeds, so setting scrape_days on them would be a silent no-op
-- (they'd keep fetching daily). That's fine for now: VC posts are infrequent, so on most days
-- VC simply has no qualifying article and is absent from the brief (no padding) — which already
-- matches the intent. If you later want a hard Wed+Sat-only VC cadence, it needs a small
-- fetcher change (extend the scrape_days gate to RSS sources too) — tracked separately, your call.
