"""
Tests for run_whatsapp_brief.resolve_length (item 3, 2026-06-22) — the consolidated length model.
A chat's `length` (short/medium/long, or None) maps onto the ONE size model (short=S / medium=M /
long=L) driving the per-theme SIZE only; theme counts come from the global writer_* values.

    venv\\Scripts\\python.exe tests\\test_length_levels.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import run_whatsapp_brief as w  # noqa: E402

PASS = []


def ok(name, cond):
    if not cond:
        raise AssertionError(name)
    PASS.append(name)


CFG = {
    "theme_size_levels": {"S": 1000, "M": 2000, "L": 4000},
    "length_to_size": {"short": "S", "medium": "M", "long": "L"},
    "default_length": "medium",
    "writer_max_themes": 5, "writer_min_themes": 3, "writer_max_articles_per_theme": 6,
    "writer_min_relevance": 6, "writer_relevance_floor": 4,
    "surfaces": {"whatsapp": {"theme_size": "M"}},
}


def test_none_uses_surface_default():
    L = w.resolve_length(CFG, None)
    ok("none_size_M", L["size"] == "M")
    ok("none_target_2000", L["per_theme_target"] == 2000)
    ok("none_themes_global", L["max_themes"] == 5)


def test_medium_maps_to_M():
    L = w.resolve_length(CFG, "medium")
    ok("med_size_M", L["size"] == "M")
    ok("med_target_2000", L["per_theme_target"] == 2000)


def test_short_maps_to_S():
    L = w.resolve_length(CFG, "short")
    ok("short_size_S", L["size"] == "S")
    ok("short_target_1000", L["per_theme_target"] == 1000)
    ok("short_themes_still_global", L["max_themes"] == 5)   # length no longer overrides theme count


def test_long_maps_to_L():
    L = w.resolve_length(CFG, "long")
    ok("long_size_L", L["size"] == "L")
    ok("long_target_4000_is_2x", L["per_theme_target"] == 4000)


def test_relevance_unchanged_across_lengths():
    for lvl in (None, "short", "long"):
        L = w.resolve_length(CFG, lvl)
        ok(f"rel_min_{lvl}", L["min_rel"] == 6)
        ok(f"rel_floor_{lvl}", L["rel_floor"] == 4)


def test_surface_theme_size_when_no_length():
    cfg2 = dict(CFG)
    cfg2["surfaces"] = {"whatsapp": {"theme_size": "L"}}
    L = w.resolve_length(cfg2, None)
    ok("surface_L_no_length", L["size"] == "L" and L["per_theme_target"] == 4000)


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
