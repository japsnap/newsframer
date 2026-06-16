-- NF-A1(b) — VC twice-weekly cadence (Wed + Sat).
-- Paired with the fetcher change (agents/fetcher.fetch_one) that makes the §8.7 scrape_days
-- calendar gate EVERY source, RSS included (it used to gate scrape sources only). With these
-- tags the 6 VC blogs fetch only Wed + Sat instead of daily; a null/blank scrape_days still
-- means 'run whenever active', so every daily source is unaffected.
-- Applied to project `openclaw` (aiabggajuzhkfnuaqqre) 2026-06-16.

UPDATE sources SET scrape_days = 'wed,sat' WHERE category = 'vc';
