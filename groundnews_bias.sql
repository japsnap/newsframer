-- NF-D1 — Ground News publication bias + factuality on `sources`.
-- Seeds the NF-NEW10 v2 left/center/right balance axis (geopolitics + pakistan clusters only).
-- Labels are the Ground News / AllSides + MBFC + Ad Fontes consensus — VERIFIED via Ground News
-- for Al Jazeera (Lean Left), Middle East Eye (Left), New York Post (Lean Right), Associated Press
-- (Lean Left), Reuters + BBC (Center); the rest are the well-established consensus. Adjust freely.
-- agents/title_dedup.normalize_bias maps 'Lean Left'->left, 'Center'->center, 'Lean Right'->right.
-- Applied to project `openclaw` (aiabggajuzhkfnuaqqre) 2026-06-16.

ALTER TABLE sources ADD COLUMN IF NOT EXISTS groundnews_publication_bias text;
ALTER TABLE sources ADD COLUMN IF NOT EXISTS groundnews_factuality text;

-- Geopolitics
UPDATE sources SET groundnews_publication_bias='Center',     groundnews_factuality='High'  WHERE name='Reuters';
UPDATE sources SET groundnews_publication_bias='Lean Left',  groundnews_factuality='High'  WHERE name='Associated Press';
UPDATE sources SET groundnews_publication_bias='Center',     groundnews_factuality='High'  WHERE name='BBC World';
UPDATE sources SET groundnews_publication_bias='Lean Left',  groundnews_factuality='Mixed' WHERE name='CNN';
UPDATE sources SET groundnews_publication_bias='Lean Left',  groundnews_factuality='High'  WHERE name='The Guardian';
UPDATE sources SET groundnews_publication_bias='Lean Left',  groundnews_factuality='High'  WHERE name='Al Jazeera';
UPDATE sources SET groundnews_publication_bias='Lean Right', groundnews_factuality='Mixed' WHERE name='New York Post';
UPDATE sources SET groundnews_publication_bias='Left',       groundnews_factuality='High'  WHERE name='Middle East Eye';
UPDATE sources SET groundnews_publication_bias='Left',       groundnews_factuality='Mixed' WHERE name='Middle East Monitor';
UPDATE sources SET groundnews_publication_bias='Lean Left',  groundnews_factuality='Mixed' WHERE name='TRT Global';
UPDATE sources SET groundnews_publication_bias='Left',       groundnews_factuality='Mixed' WHERE name='Zeteo';
UPDATE sources SET groundnews_publication_bias='Left',       groundnews_factuality='Mixed' WHERE name='Heather Cox Richardson';
UPDATE sources SET groundnews_publication_bias='Center',     groundnews_factuality='Mixed' WHERE name='Noahpinion';

-- Pakistan
UPDATE sources SET groundnews_publication_bias='Center',     groundnews_factuality='High'  WHERE name='Dawn';
UPDATE sources SET groundnews_publication_bias='Center',     groundnews_factuality='High'  WHERE name='The Express Tribune';
UPDATE sources SET groundnews_publication_bias='Lean Right', groundnews_factuality='Mixed' WHERE name='The News International';
