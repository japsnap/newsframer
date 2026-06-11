"""
Tests for agents/bundle_floors.py — per-bundle theme allocation (spec §8.1/§8.6).

Pure logic: label clusters by source-category bundle, then select themes so that
every ACTIVE bundle is guaranteed its floor of themes, no bundle exceeds its cap,
and the total scales with the number of active bundles. No DB, no LLM.

    venv\\Scripts\\python.exe tests\\test_bundle_floors.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
import bundle_floors as bf  # noqa: E402

PASS = []


def ok(name, cond):
    if not cond:
        raise AssertionError(name)
    PASS.append(name)


SC = {"c": "crypto", "g": "geopolitics", "p": "pakistan", "y": "cybersecurity", "t": "tech"}
FLOORS = {"crypto": 1, "geopolitics": 1, "pakistan": 1, "cybersecurity": 1, "tech": 1}


def cl(*letters):
    """A cluster of articles from the given source letters."""
    return [{"id": f"{l}-{i}", "source_id": l} for i, l in enumerate(letters)]


def sel(clusters, cap=2, mult=1.5, tmax=10):
    return bf.select_themes_with_floors(clusters, SC, FLOORS, cap, mult, tmax)


# --- cluster_bundle --------------------------------------------------------
def test_dominant_category():
    ok("dominant", bf.cluster_bundle(cl("c", "c", "t"), SC) == "crypto")


def test_tie_uses_first_article():
    ok("tie_first", bf.cluster_bundle(cl("c", "t"), SC) == "crypto")


def test_empty_cluster_none():
    ok("empty_none", bf.cluster_bundle([{"source_id": "zzz"}], SC) is None)


# --- crowding fix (the core requirement) -----------------------------------
def test_high_volume_does_not_crowd_out_low():
    clusters = [cl("c"), cl("c"), cl("c"), cl("c"), cl("c"), cl("g"), cl("y")]
    themes, leftovers, rep = sel(clusters)
    ok("crowd_before_crypto_heavy", rep["before"].get("crypto", 0) >= 3)
    ok("crowd_after_crypto_capped", rep["after"].get("crypto", 0) <= 2)
    ok("crowd_geo_retained", rep["after"].get("geopolitics", 0) >= 1)
    ok("crowd_cyber_retained", rep["after"].get("cybersecurity", 0) >= 1)
    ok("crowd_cyber_in_themes", any(bf.cluster_bundle(t, SC) == "cybersecurity" for t in themes))


def test_single_article_low_volume_bundle_kept():
    clusters = [cl("c"), cl("c"), cl("t")]  # tech has one single-article cluster
    themes, leftovers, rep = sel(clusters)
    ok("single_tech_kept", rep["after"].get("tech", 0) >= 1)


def test_cap_is_respected():
    clusters = [cl("c")] * 5  # all crypto
    themes, leftovers, rep = sel(clusters, cap=2)
    ok("cap_crypto_two", rep["after"].get("crypto", 0) == 2)
    ok("cap_total_two", rep["theme_count"] == 2)


def test_absent_bundle_not_padded():
    clusters = [cl("c"), cl("g")]  # no pakistan/cyber/tech
    themes, leftovers, rep = sel(clusters)
    ok("absent_no_pakistan", rep["after"].get("pakistan", 0) == 0)
    ok("absent_no_cyber", rep["after"].get("cybersecurity", 0) == 0)


def test_dynamic_total_scales_with_active_bundles():
    # 5 active bundles, extra clusters for c/g/t -> target ceil(1.5*5)=8
    clusters = [cl("c"), cl("g"), cl("t"), cl("p"), cl("y"), cl("c"), cl("g"), cl("t")]
    themes, leftovers, rep = sel(clusters)
    ok("dyn_num_active", rep["num_active"] == 5)
    ok("dyn_target8", rep["target_total"] == 8)
    ok("dyn_count8", rep["theme_count"] == 8)
    ok("dyn_each_le_cap", all(v <= 2 for v in rep["after"].values()))
    ok("dyn_each_ge_floor", all(rep["after"].get(b, 0) >= 1 for b in ("crypto", "geopolitics", "pakistan", "cybersecurity", "tech")))


def test_leftovers_are_unselected_articles():
    clusters = [cl("c")] * 5
    themes, leftovers, rep = sel(clusters, cap=2)
    # 5 crypto clusters, 2 selected -> 3 clusters' articles are leftovers
    ok("leftover_count", len(leftovers) == 3)


def test_report_keys_present():
    _, _, rep = sel([cl("c"), cl("g")])
    ok("report_keys", all(k in rep for k in ("before", "after", "target_total", "num_active", "theme_count")))


def main():
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
            except AssertionError as e:
                print(f"FAIL: {e}")
                failed += 1
            except Exception as e:
                print(f"ERROR in {name}: {type(e).__name__}: {e}")
                failed += 1
    print(f"\n{len(PASS)} checks passed, {failed} test(s) failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
