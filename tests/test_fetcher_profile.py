"""
Tests for NF-NEW11 — fetcher.resolve_fetch_caps (full vs light fetch profile).
Pure: no network, no DB. The hard requirement is NON-BREAKING — a missing or 'full'
profile must reproduce today's 100/source full-day caps exactly.

    venv\\Scripts\\python.exe tests\\test_fetcher_profile.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
import fetcher as f  # noqa: E402

PASS = []


def ok(name, cond):
    if not cond:
        raise AssertionError(name)
    PASS.append(name)


# Mirrors the live config/models.yaml values.
FULL_CFG = {
    "fetch_profile": "full",
    "max_articles_per_source": 100,
    "fetch_safety_ceiling": 3000,
    "fetch_light_max_per_source": 10,
    "fetch_light_safety_ceiling": 600,
}


def test_full_profile_uses_full_caps():
    profile, mps, ceil = f.resolve_fetch_caps(FULL_CFG)
    ok("full_label", profile == "full")
    ok("full_mps", mps == 100)
    ok("full_ceiling", ceil == 3000)


def test_light_profile_uses_light_caps():
    cfg = dict(FULL_CFG, fetch_profile="light")
    profile, mps, ceil = f.resolve_fetch_caps(cfg)
    ok("light_label", profile == "light")
    ok("light_mps", mps == 10)
    ok("light_ceiling", ceil == 600)


def test_light_is_case_and_space_insensitive():
    profile, mps, _ = f.resolve_fetch_caps(dict(FULL_CFG, fetch_profile="  LIGHT "))
    ok("light_normalized", profile == "light" and mps == 10)


def test_missing_profile_defaults_to_full():
    cfg = {"max_articles_per_source": 100, "fetch_safety_ceiling": 3000}
    profile, mps, ceil = f.resolve_fetch_caps(cfg)
    ok("missing_is_full", profile == "full")
    ok("missing_full_mps", mps == 100)
    ok("missing_full_ceiling", ceil == 3000)


def test_unknown_profile_falls_back_to_full():
    profile, mps, ceil = f.resolve_fetch_caps(dict(FULL_CFG, fetch_profile="turbo"))
    ok("unknown_is_full", profile == "full" and mps == 100 and ceil == 3000)


def test_empty_config_reproduces_hardcoded_defaults():
    # A hollow config must fall back to the SAME defaults the old inline code used (10 / 600).
    profile, mps, ceil = f.resolve_fetch_caps({})
    ok("empty_full", profile == "full")
    ok("empty_mps_default", mps == 10)
    ok("empty_ceiling_default", ceil == 600)


def test_none_values_use_defaults():
    cfg = {"fetch_profile": None, "max_articles_per_source": None, "fetch_safety_ceiling": None}
    profile, mps, ceil = f.resolve_fetch_caps(cfg)
    ok("none_profile_full", profile == "full")
    ok("none_mps_default", mps == 10)
    ok("none_ceiling_default", ceil == 600)


def test_light_ceiling_is_int():
    _, _, ceil = f.resolve_fetch_caps(dict(FULL_CFG, fetch_profile="light", fetch_light_safety_ceiling="600"))
    ok("ceiling_coerced_int", ceil == 600 and isinstance(ceil, int))


def test_tolerant_of_broken_config():
    class Boom:
        def get(self, *a):
            raise RuntimeError("boom")
    profile, mps, ceil = f.resolve_fetch_caps(Boom())
    ok("broken_safe", profile == "full" and mps == 10 and ceil == 600)


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
