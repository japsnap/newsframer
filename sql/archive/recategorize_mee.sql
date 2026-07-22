-- ARCHIVED 2026-07-22 — one-off DATA migration, already applied to the live DB (2026-06-15).
-- Not needed on a fresh install: sql/seed_sources.sql ships Middle East Eye with category='geopolitics'
-- already. Kept for provenance only. Reversible: set category back to 'investigative' to undo.
--
-- recategorize_mee.sql  (NF-NEW3, 2026-06-15) — RUN AT HOME against the live Supabase.
--
-- WHY: Middle East Eye is tagged category='investigative', but it is a Middle East
-- NEWS outlet (incl. a high-volume live-blog), not an OSINT/investigative shop. The
-- 'investigative' bundle is pulled OUT of the main brief themes and shown only as
-- "Investigations" drops, so MEE's news (a) never reaches the normal themes and (b)
-- floods the Investigations section — on 2026-06-15 all 3 Investigations items were
-- MEE /live-blog/ updates about the US-Iran deal.
--
-- FIX: move MEE to 'geopolitics' so its news competes in the normal themes, and the
-- Investigations section is left for true investigative/OSINT sources (Bellingcat,
-- Citizen Lab, Forensic Architecture, Amnesty labs, Forbidden Stories, EFF, TechNadu).
-- Reversible: set category back to 'investigative' to undo.

update sources
set category = 'geopolitics'
where name = 'Middle East Eye' and category = 'investigative';

-- Optional — reconsider these too (more news/opinion than OSINT). Uncomment to apply:
-- update sources set category = 'geopolitics' where name = '+972 Magazine'  and category = 'investigative';
-- update sources set category = 'geopolitics' where name = 'The Intercept'  and category = 'investigative';
