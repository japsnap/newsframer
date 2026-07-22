-- NewsFramer — user_context EXAMPLE seed (INVENTED PLACEHOLDER DATA ONLY).
-- Run AFTER sql/schema.sql, but FIRST replace every row below with your own interests and hypotheses.
-- These generic examples are here only to show the shape — they are NOT anyone's real interests.
--
-- Two kinds of row:
--   kind='interest'   — a topic you care about, with a signed `weight` (relevance nudge, e.g. +3..-3).
--   kind='hypothesis' — a directional claim you're tracking; the Analyst labels each article as
--                        confirming / challenging / neutral against your ACTIVE hypotheses.
-- Only rows with active=true and a live status feed the Analyst. The pipeline runs fine with zero rows.

-- Sample interests (replace topics + weights with your own):
insert into user_context (kind, topic, weight, active, status) values
  ('interest', 'open-source developer tooling',        3, true, 'active'),
  ('interest', 'renewable-energy grid storage',        2, true, 'active'),
  ('interest', 'celebrity gossip',                     -2, true, 'active');

-- Sample hypothesis (one invented, testable claim — replace with your own):
insert into user_context (kind, topic, stance, confidence, reasoning, specificity, status, active) values
  ('hypothesis',
   'Small on-device AI models will displace cloud API calls for most consumer app features by 2027',
   'agree', 5,
   'Placeholder reasoning — state why you hold this and what evidence would change your mind.',
   'specific', 'active', true);
