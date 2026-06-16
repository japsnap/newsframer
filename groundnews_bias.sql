-- NF-D1 — Ground News publication bias + factuality on `sources`.
-- Seeds the NF-NEW10 left/center/right balance axis (geopolitics + pakistan clusters only).
-- 3 CATEGORIES ONLY (operator 2026-06-16): left / center / right — the "Lean" gradations are
-- collapsed (Lean Left -> left, Lean Right -> right). Labels are the Ground News / AllSides + MBFC
-- consensus — verified via Ground News for Al Jazeera, Middle East Eye, New York Post, Associated
-- Press, Reuters, BBC; the rest are the well-established consensus. Adjust freely.
-- Applied to project `openclaw` (aiabggajuzhkfnuaqqre).

ALTER TABLE sources ADD COLUMN IF NOT EXISTS groundnews_publication_bias text;
ALTER TABLE sources ADD COLUMN IF NOT EXISTS groundnews_factuality text;

-- Geopolitics
UPDATE sources SET groundnews_publication_bias='center', groundnews_factuality='High'  WHERE name='Reuters';
UPDATE sources SET groundnews_publication_bias='left',   groundnews_factuality='High'  WHERE name='Associated Press';
UPDATE sources SET groundnews_publication_bias='center', groundnews_factuality='High'  WHERE name='BBC World';
UPDATE sources SET groundnews_publication_bias='left',   groundnews_factuality='Mixed' WHERE name='CNN';
UPDATE sources SET groundnews_publication_bias='left',   groundnews_factuality='High'  WHERE name='The Guardian';
UPDATE sources SET groundnews_publication_bias='left',   groundnews_factuality='High'  WHERE name='Al Jazeera';
UPDATE sources SET groundnews_publication_bias='right',  groundnews_factuality='Mixed' WHERE name='New York Post';
UPDATE sources SET groundnews_publication_bias='left',   groundnews_factuality='High'  WHERE name='Middle East Eye';
UPDATE sources SET groundnews_publication_bias='left',   groundnews_factuality='Mixed' WHERE name='Middle East Monitor';
UPDATE sources SET groundnews_publication_bias='left',   groundnews_factuality='Mixed' WHERE name='TRT Global';
UPDATE sources SET groundnews_publication_bias='left',   groundnews_factuality='Mixed' WHERE name='Zeteo';
UPDATE sources SET groundnews_publication_bias='left',   groundnews_factuality='Mixed' WHERE name='Heather Cox Richardson';
UPDATE sources SET groundnews_publication_bias='center', groundnews_factuality='Mixed' WHERE name='Noahpinion';

-- Pakistan
UPDATE sources SET groundnews_publication_bias='center', groundnews_factuality='High'  WHERE name='Dawn';
UPDATE sources SET groundnews_publication_bias='center', groundnews_factuality='High'  WHERE name='The Express Tribune';
UPDATE sources SET groundnews_publication_bias='right',  groundnews_factuality='Mixed' WHERE name='The News International';
