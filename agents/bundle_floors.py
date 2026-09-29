"""
Per-bundle theme allocation (spec §8.1 / §8.6) — pure logic.

High-volume bundles (e.g. crypto) can crowd low-frequency ones (cybersecurity)
out of the brief's themes. This re-allocates which already-formed clusters become
themes so that every ACTIVE bundle is guaranteed a minimum (floor), no bundle
monopolizes (cap), and the total theme count scales with how many bundles are
actually present. It does NOT cluster, score, or rank — clustering happens in
writer.cluster_by_topic_overlap (unchanged); this only picks among the result.

A "bundle" is an article's source.category. A cluster's bundle is the dominant
category among its articles (ties -> the top-ranked article's category). A bundle
with no qualifying cluster is simply absent — nothing stale is padded in (§4.5).
"""
import math
from collections import Counter


def cluster_bundle(cluster, source_cat):
    """The bundle (source category) a cluster belongs to: the most common category
    among its articles; ties resolved by the first (highest-composite) article."""
    cats = [source_cat.get(a.get("source_id")) for a in cluster]
    cats = [c for c in cats if c]
    if not cats:
        return None
    counts = Counter(cats)
    top = max(counts.values())
    leaders = {c for c in cats if counts[c] == top}
    if len(leaders) == 1:
        return next(iter(leaders))
    return source_cat.get(cluster[0].get("source_id")) or next(iter(leaders))


def select_themes_with_floors(all_clusters, source_cat, floors, cap, multiplier, theme_count_max):
    """Choose which clusters become themes.

    all_clusters: every cluster, already ranked best-first by composite score.
    floors: {bundle: min_themes}. cap: max themes any one bundle may take.
    multiplier: total target = ceil(multiplier * number of active bundles).
    theme_count_max: absolute safety ceiling on the total.

    Returns (themes, leftover_articles, report). `report` carries per-bundle
    before/after counts for the dry-run.
    """
    labeled = [(c, cluster_bundle(c, source_cat)) for c in all_clusters]
    active = {b for _, b in labeled if b in floors}
    num_active = len(active)

    target = math.ceil(multiplier * num_active) if num_active else 0
    target = min(target, theme_count_max)
    target = max(target, num_active)  # never below one-per-active-bundle

    before = Counter(b for _, b in labeled[:target] if b)

    chosen = []        # selected indices, in selection order
    chosen_set = set()
    per = Counter()

    # Floor pass: each active bundle gets up to its floor (never exceeding the cap).
    for bundle, fmin in floors.items():
        for i, (c, b) in enumerate(labeled):
            if per[bundle] >= min(fmin, cap):
                break
            if i in chosen_set or b != bundle:
                continue
            chosen.append(i); chosen_set.add(i); per[bundle] += 1

    # Fill pass: by score rank, up to the target, never exceeding any bundle's cap.
    for i, (c, b) in enumerate(labeled):
        if len(chosen) >= target:
            break
        if i in chosen_set or b is None or per[b] >= cap:
            continue
        chosen.append(i); chosen_set.add(i); per[b] += 1

    order = sorted(chosen)  # present themes best-first (by composite rank)
    themes = [labeled[i][0] for i in order]
    leftovers = [a for i, (c, b) in enumerate(labeled) if i not in chosen_set for a in c]
    after = Counter(cluster_bundle(t, source_cat) for t in themes)

    report = {
        "before": dict(before),
        "after": dict(after),
        "target_total": target,
        "num_active": num_active,
        "theme_count": len(themes),
    }
    return themes, leftovers, report
