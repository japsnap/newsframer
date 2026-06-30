"""
Config-integrity guard: every COST-INCURRING model referenced in config/models.yaml must
have a pricing entry (with input AND output), so its spend is actually tracked. A model
configured with no pricing logs cost as $0 silently — the bill stops diagnosing itself
(CLAUDE.md). This fails loudly if that ever happens.

Scope is narrow + false-positive-free: only `*_model` keys that drive a paid LLM call are
checked. The fetcher uses no model, and the embedding model is priced separately — both
are excluded explicitly.

    venv\\Scripts\\python.exe tests\\test_config_integrity.py
"""
import os
import sys

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Not a paid (metered) text-completion model -> no pricing entry expected. fetcher uses no model; the
# embedding model is priced separately; the *_subscription_model keys run on the flat Max subscription
# via `claude -p` (no per-token price by design — their agent_runs cost is logged as $0).
EXCLUDE = {"fetcher_model", "deduplicator_embedding_model",
           "writer_subscription_model", "analyst_subscription_model"}
PASS = []


def ok(name, cond):
    if not cond:
        raise AssertionError(name)
    PASS.append(name)


def load_cfg():
    with open(os.path.join(ROOT, "config", "models.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def cost_model_keys(cfg):
    return [k for k in cfg if k.endswith("_model") and k not in EXCLUDE]


def missing_pricing(cfg):
    """Return [(key, model)] for cost models whose model has no usable pricing entry."""
    pricing = cfg.get("pricing") or {}
    bad = []
    for k in cost_model_keys(cfg):
        model = cfg.get(k)
        entry = pricing.get(model)
        if not (isinstance(entry, dict) and "input" in entry and "output" in entry):
            bad.append((k, model))
    return bad


def test_every_cost_model_has_pricing():
    cfg = load_cfg()
    ok("found_cost_models", len(cost_model_keys(cfg)) >= 4)
    bad = missing_pricing(cfg)
    ok("all_priced [" + ("; ".join(f"{k}={m}" for k, m in bad) if bad else "clean") + "]", not bad)


def test_pricing_entries_have_both_fields():
    cfg = load_cfg()
    for model, entry in (cfg.get("pricing") or {}).items():
        if isinstance(entry, dict):
            ok(f"input:{model}", "input" in entry)
            ok(f"output:{model}", "output" in entry)


def test_detector_catches_a_missing_price():
    # If the guard can't catch the very thing it guards, the green above is hollow.
    fake = {"writer_model": "some/unpriced-model", "analyst_model": "gemini/x",
            "classifier_model": "gemini/x", "drop_report_model": "gemini/x",
            "pricing": {"gemini/x": {"input": 1, "output": 2}}}
    bad = missing_pricing(fake)
    ok("catches_unpriced", ("writer_model", "some/unpriced-model") in bad)
    ok("ignores_priced", ("analyst_model", "gemini/x") not in bad)


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
