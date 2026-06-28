"""
Topic cadence classes (NF-NEW14, spec §8.1/§8.6) — pure logic.

Every source category (bundle) belongs to a CADENCE CLASS that decides how its content is selected
for the brief. The point: daily news and low-frequency/curated topics need fundamentally different
handling, and which-is-which must be CONFIG, not code — so adding a topic is "assign it a class".

A class controls three things:
  - window_hours       : how far back selection reaches for that category. A twice-weekly topic
                         judged on a 24h window is mostly invisible; low-frequency classes reach
                         back far enough to cover their cadence.
  - relevance_bar      : the entry bar an article must clear. Low-frequency curated essays (VC blogs)
                         score low against daily-news interests but are worth surfacing — lower bar.
  - min_theme_articles : how many articles a CLUSTER needs to stand as its own theme. Regular daily
                         news needs a real multi-source cluster (no lone-article daily theme); a
                         low-frequency topic may stand alone (each rare post counts).

Defaults: an unmapped category -> `default_class`. A class missing a field falls back to the global
value (window_hours -> writer_window_hours; relevance_bar -> writer_min_relevance;
min_theme_articles -> 1, i.e. today's "a single-article cluster may be a theme").

Cross-run duplication (the same story re-sent across the twice-weekly slots) is NOT handled here — it
is prevented upstream by the §4.3 deliveries set-difference (a delivered article is excluded from
later briefs), so a wider window never re-sends.
"""
from datetime import datetime, timezone

DEFAULT_CLASS = "regular"


def _age_hours(published_at, now):
    """Hours between published_at (ISO string) and `now`; None if missing/unparseable."""
    if not published_at:
        return None
    try:
        dt = datetime.fromisoformat(str(published_at).replace("Z", "+00:00"))
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (now - dt).total_seconds() / 3600.0


class TopicClasses:
    """Config-bound resolver. Construct once per run from config + the global writer knobs, then ask
    it per-category / per-article / per-cluster. With NO category mapped (category_classes empty) and
    every default falling through, behaviour is identical to a single global window + gate."""

    def __init__(self, category_classes, classes, default_class, global_window, global_bar,
                 floor_keeps_single=True):
        self.category_classes = category_classes or {}
        self.classes = classes or {}
        self.default_class = default_class or DEFAULT_CLASS
        self.global_window = int(global_window)
        self.global_bar = int(global_bar)
        # Option B (default): each active category keeps its ONE best story as a theme even when
        # single-source; only ADDITIONAL themes from that category must meet min_theme_articles.
        # False = strict: a sub-minimum cluster is always a highlight, never a theme.
        self.floor_keeps_single = bool(floor_keeps_single)

    # --- resolvers ---------------------------------------------------------
    def class_of(self, category):
        return self.category_classes.get(category) or self.default_class

    def _def(self, category):
        d = self.classes.get(self.class_of(category))
        return d if isinstance(d, dict) else {}

    def window_for(self, category):
        w = self._def(category).get("window_hours")
        return int(w) if w else self.global_window

    def bar_for(self, category):
        b = self._def(category).get("relevance_bar")
        return int(b) if b is not None else self.global_bar

    def min_theme_articles_for(self, category):
        m = self._def(category).get("min_theme_articles")
        return int(m) if m is not None else 1

    def max_window(self):
        """The widest window the writer must LOAD before age-filtering each category to its own."""
        windows = [self.global_window]
        names = {self.default_class} | set(self.category_classes.values())  # only classes IN USE
        for n in names:
            d = self.classes.get(n)
            if isinstance(d, dict) and d.get("window_hours"):
                windows.append(int(d["window_hours"]))
        return max(windows)

    def bars_map(self):
        """{category: bar} for every mapped category whose bar differs from the global gate."""
        out = {}
        for cat in self.category_classes:
            b = self.bar_for(cat)
            if b != self.global_bar:
                out[cat] = b
        return out

    # --- selection passes --------------------------------------------------
    def filter_to_windows(self, articles, now, bundle_of):
        """Keep each article only if within ITS category's window. Missing/unparseable dates are kept
        (treated as fresh — matches the fetcher's now()-default for dateless items)."""
        kept = []
        for a in articles:
            age = _age_hours(a.get("published_at"), now)
            if age is None or age <= self.window_for(bundle_of(a)):
                kept.append(a)
        return kept

    def filter_qualifying(self, candidates, rel_floor, min_themes, bundle_of, actionability_floor=2):
        """The §4.5 relevance gate, PER-CATEGORY. An article qualifies if relevance >= its category's
        bar (default = global gate) OR actionability >= actionability_floor. A global `relax` backoff
        lowers every bar uniformly (down to a floor of 1) until >= min_themes qualify — same thin-day
        relaxation as before. With no category mapped this equals the old single-threshold backoff
        from global_bar down to rel_floor. Returns (qualifying, chosen_relax)."""
        max_relax = max(0, self.global_bar - int(rel_floor))
        chosen, relax = [], 0
        for relax in range(0, max_relax + 1):
            chosen = []
            for a in candidates:
                s = a.get("score") or {}
                rel = s.get("relevance_score") or 0
                act = s.get("actionability") or 0
                bar = max(1, self.bar_for(bundle_of(a)) - relax)
                if rel >= bar or act >= actionability_floor:
                    chosen.append(a)
            if len(chosen) >= min_themes:
                break
        return chosen, relax

    def eligible_clusters(self, clusters, cluster_category):
        """Split ranked-best-first clusters into (theme_eligible, dropped).

        A cluster is theme-eligible if it meets its class's min_theme_articles, OR (when
        floor_keeps_single, option B) it is the FIRST/top-ranked cluster of its category — so every
        active category keeps its single best story as a theme, while ADDITIONAL themes from that
        category must meet the class minimum (no single-article clutter). Dropped clusters' articles
        fall back to the highlight pool. `clusters` MUST be ranked best-first; `cluster_category(c)
        -> category`."""
        eligible, dropped = [], []
        seen = set()
        for c in clusters:
            cat = cluster_category(c)
            is_top = self.floor_keeps_single and cat is not None and cat not in seen
            seen.add(cat)
            if len(c) >= self.min_theme_articles_for(cat) or is_top:
                eligible.append(c)
            else:
                dropped.append(c)
        return eligible, dropped
