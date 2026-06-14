"""
Validates the LIVE theme-scaling config (config/models.yaml) against the §8.1/§8.6
requirement Shota set: VC and tech are SEPARATE bundles, the theme count scales with
the number of active bundles, every active bundle appears at least once when it has a
qualifying article, and a bundle with no news is simply absent (no padding).

Loads the real config (not a synthetic floor set), so a misnamed/missing bundle or a
ceiling set below the bundle count fails here at test time.

    venv\\Scripts\\python.exe tests\\test_theme_scaling_config.py
"""
import os
import sys

import yaml

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "agents"))
import bundle_floors as bf  # noqa: E402

PASS = []


def ok(name, cond):
    if not cond:
        raise AssertionError(name)
    PASS.append(name)


with open(os.path.join(ROOT, "config", "models.yaml"), encoding="utf-8") as f:
    CFG = yaml.safe_load(f)

FLOORS = CFG["bundle_theme_floors"]
CAP = CFG["bundle_theme_cap"]
MULT = CFG["theme_count_multiplier"]
TMAX = CFG["theme_count_max"]
BUNDLES = list(FLOORS.keys())
# source_id -> category, one synthetic source per bundle
SRC = {b: b for b in BUNDLES}


def singleton(bundle, i=0):
    """A one-article cluster belonging to `bundle`."""
    return [{"id": f"{bundle}-{i}", "source_id": bundle}]


# --- the split Shota asked for ---------------------------------------------
def test_vc_and_tech_are_separate_floored_bundles():
    ok("vc_in_floors", "vc" in FLOORS)
    ok("tech_in_floors", "tech" in FLOORS)
    ok("vc_floor_ge_1", FLOORS["vc"] >= 1)
    ok("tech_floor_ge_1", FLOORS["tech"] >= 1)


def test_ceiling_cannot_starve_a_bundle():
    # the absolute ceiling must be >= the number of floored bundles, else a bundle
    # could be denied its floor on a fully-active day.
    ok("ceiling_ge_bundle_count", TMAX >= len(BUNDLES))


# --- each active bundle appears at least once ------------------------------
def test_every_active_bundle_gets_a_theme():
    clusters = [singleton(b) for b in BUNDLES]  # one qualifying article per bundle
    themes, leftovers, rep = bf.select_themes_with_floors(clusters, SRC, FLOORS, CAP, MULT, TMAX)
    for b in BUNDLES:
        ok(f"appears_{b}", rep["after"].get(b, 0) >= 1)
    ok("count_eq_bundles", rep["theme_count"] == len(BUNDLES))
    ok("num_active_all", rep["num_active"] == len(BUNDLES))


# --- high-volume bundle can't monopolise; others still appear --------------
def test_high_volume_bundle_capped_others_kept():
    clusters = [singleton("crypto", i) for i in range(5)] + [singleton(b) for b in BUNDLES if b != "crypto"]
    themes, leftovers, rep = bf.select_themes_with_floors(clusters, SRC, FLOORS, CAP, MULT, TMAX)
    ok("crypto_capped", rep["after"].get("crypto", 0) <= CAP)
    for b in BUNDLES:
        ok(f"kept_{b}", rep["after"].get(b, 0) >= 1)


# --- a bundle with no qualifying news is simply absent (no padding) --------
def test_absent_bundle_not_padded():
    present = [b for b in BUNDLES if b != "vc"]  # vc has nothing this day
    clusters = [singleton(b) for b in present]
    themes, leftovers, rep = bf.select_themes_with_floors(clusters, SRC, FLOORS, CAP, MULT, TMAX)
    ok("vc_absent", rep["after"].get("vc", 0) == 0)
    ok("active_excludes_vc", rep["num_active"] == len(present))


# --- target scales with the number of active bundles -----------------------
def test_target_scales_with_active_bundles():
    import math
    # give every bundle enough clusters that the fill pass is cluster-unbounded
    clusters = [singleton(b, i) for b in BUNDLES for i in range(CAP)]
    themes, leftovers, rep = bf.select_themes_with_floors(clusters, SRC, FLOORS, CAP, MULT, TMAX)
    expected = min(max(math.ceil(MULT * len(BUNDLES)), len(BUNDLES)), TMAX)
    ok("target_matches_formula", rep["target_total"] == expected)
    ok("scales_above_floor_count", rep["target_total"] >= len(BUNDLES))


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
