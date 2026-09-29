-- NewsFramer — junk-pattern seed data (URL / title filters applied at fetch).
-- Run AFTER sql/schema.sql. pattern_type is one of: url_contains, url_endswith, title_contains.

insert into junk_patterns (pattern, pattern_type, confidence, active) values
  ('/feed', 'url_endswith', 9, true),
  ('coupon code', 'title_contains', 8, true),
  ('knowledgehub.wiley', 'url_contains', 9, true),
  ('mailto:', 'url_contains', 10, true),
  ('nypost.com/coupons', 'url_contains', 9, true),
  ('preview', 'title_contains', 7, true),
  ('promo code', 'title_contains', 8, true),
  ('select-plan', 'url_contains', 10, true),
  ('sign up', 'title_contains', 8, true),
  ('subscribe', 'title_contains', 8, true),
  ('wikipedia.org', 'url_contains', 9, true),
  ('x.com/', 'url_contains', 7, true);
