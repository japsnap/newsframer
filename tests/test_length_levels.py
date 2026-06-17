"""
Tests for run_whatsapp_brief.resolve_length (NF-E2 / §6) — per-chat brief length levels.
Pure config resolution: a level overrides only the knobs it lists; the rest fall back to the
global writer_* values, and 'medium' (empty) reproduces today's behaviour.

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
    "writer_max_themes": 5, "writer_min_themes": 3, "writer_per_theme_chars": 2500,
    "writer_max_articles_per_theme": 6, "writer_max_chars_floor": 6000, "writer_max_chars_ceiling": 16000,
    "writer_min_relevance": 6, "writer_relevance_floor": 4,
    "default_length": "medium",
    "length_levels": {
        "short": {"max_themes": 3, "min_themes": 2, "per_theme_chars": 1200, "max_articles_per_theme": 3},
        "medium": {},
        "long": {"max_themes": 8, "per_theme_chars": 3500, "max_articles_per_theme": 8, "max_chars_ceiling": 22000},
    },
}


def test_medium_equals_globals():
    L = w.resolve_length(CFG, "medium")
    ok("med_themes", L["max_themes"] == 5)
    ok("med_chars", L["per_theme_chars"] == 2500)
    ok("med_ceiling", L["ceiling"] == 16000)
    ok("med_per_theme", L["max_per_theme"] == 6)


def test_short_overrides_with_fallback():
    L = w.resolve_length(CFG, "short")
    ok("short_themes", L["max_themes"] == 3)
    ok("short_chars", L["per_theme_chars"] == 1200)
    ok("short_min_themes", L["min_themes"] == 2)
    ok("short_per_theme", L["max_per_theme"] == 3)
    ok("short_ceiling_fallback", L["ceiling"] == 16000)   # not overridden -> global


def test_long_overrides():
    L = w.resolve_length(CFG, "long")
    ok("long_themes", L["max_themes"] == 8)
    ok("long_chars", L["per_theme_chars"] == 3500)
    ok("long_ceiling", L["ceiling"] == 22000)


def test_none_uses_default():
    L = w.resolve_length(CFG, None)
    ok("none_default_themes", L["max_themes"] == 5)
    ok("none_default_label", L["level"] == "medium")


def test_unknown_level_falls_back_to_globals():
    L = w.resolve_length(CFG, "bogus")
    ok("unknown_globals", L["max_themes"] == 5 and L["per_theme_chars"] == 2500)


def test_missing_levels_block_uses_globals():
    cfg2 = {k: v for k, v in CFG.items() if k != "length_levels"}
    ok("no_block_globals", w.resolve_length(cfg2, "short")["max_themes"] == 5)


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
