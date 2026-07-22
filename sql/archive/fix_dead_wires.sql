-- ARCHIVED 2026-07-22 — one-off DATA migration, already applied to the live DB (2026-06-15).
-- Not needed on a fresh install: sql/seed_sources.sql already ships Reuters / Associated Press / CNN
-- with the Google-News-RSS rss_url and active=true. Kept for provenance only.
--
-- fix_dead_wires.sql — 2026-06-15 (operator-approved)
-- Reuters, Associated Press, and CNN have all dropped or frozen their official RSS:
--   * feeds.reuters.com  -> DNS-dead (Reuters discontinued RSS in 2020)
--   * feeds.apnews.com   -> DNS-dead (no working public AP feed)
--   * rss.cnn.com/*      -> frozen, newest item ~Apr 2023
-- The only fresh, real-RSS route is a Google News RSS search feed (verified 100 fresh
-- items). Caveat: article links are Google-redirect URLs with short snippets (a proxy,
-- not the publisher's own feed). Reuters/AP were active=false; reactivate them.
-- RSS-only change; no code touched.

UPDATE sources
SET rss_url = 'https://news.google.com/rss/search?q=site:reuters.com+when:1d&hl=en-US&gl=US&ceid=US:en',
    has_rss = true,
    active  = true
WHERE name = 'Reuters';

UPDATE sources
SET rss_url = 'https://news.google.com/rss/search?q=site:apnews.com+when:1d&hl=en-US&gl=US&ceid=US:en',
    has_rss = true,
    active  = true
WHERE name = 'Associated Press';

UPDATE sources
SET rss_url = 'https://news.google.com/rss/search?q=site:cnn.com+when:1d&hl=en-US&gl=US&ceid=US:en',
    has_rss = true,
    active  = true
WHERE name = 'CNN';
