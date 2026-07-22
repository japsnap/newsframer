-- ARCHIVED 2026-07-22 — one-off DATA migration, already applied to the live DB (2026-06-30).
-- Not needed on a fresh install: sql/seed_sources.sql ships Center for Spatial Technologies with
-- active=true already. Kept for provenance only. Reversible: set active=false.
--
-- NF-A4 (2026-06-30): activate Center for Spatial Technologies (CST) as a SCRAPE source.
-- CST has no RSS (has_rss=false); site_url=https://spatialtech.info/; scrape_days='thu' (§8.7 calendar).
-- Firecrawl listing-scrape verified read-only: returns 10 real project pages (Mariupol Drama Theater,
-- Babyn Yar, TV Tower reconstruction, ...). "Scrape em" = flip active on. Reversible: set active=false.
UPDATE sources
SET active = true
WHERE id = '7e394c75-2e96-4207-95b7-c0ff51cba0cd';  -- Center for Spatial Technologies
