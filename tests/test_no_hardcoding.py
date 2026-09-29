"""
Enforcement test for the no-hardcoding hard rule (CLAUDE.md): every operational
tunable lives in config/models.yaml and is read with config.get(key, default).

The most common regression of that rule is passing an LLM call parameter
(temperature / max_tokens / …) as a BARE NUMBER straight into the call instead of
through config. This test scans the engine code for exactly that and fails if a
new one appears.

Scope is deliberately NARROW to stay false-positive-free: only LLM-call kwargs are
checked — temperature, max_tokens, max_output_tokens, top_p, presence_penalty,
frequency_penalty — and only when the value is a bare numeric literal. It does NOT
scan every number in the code (array indices, HTTP status codes, ranges, slice
lengths) — that would be noise, not signal. A bare-literal DEFAULT inside
config.get(...) (e.g. config.get("writer_temperature", 0.3)) is correct and is NOT
flagged, because the regex only fires when a digit follows the '=' directly.

    venv\\Scripts\\python.exe tests\\test_no_hardcoding.py
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# LLM-call params that must be config-driven, never a bare literal.
PARAMS = ("temperature", "max_tokens", "max_output_tokens", "top_p",
          "presence_penalty", "frequency_penalty")
# Fires only when a digit (optionally signed) follows '=' directly. A config.get
# default or a variable starts with a letter/paren, so neither is flagged.
BARE = re.compile(r"\b(?:" + "|".join(PARAMS) + r")\s*=\s*[-+]?\d")

SCAN_DIRS = ["agents"]
SCAN_FILES = ["deliver_brief.py", "run_brief.py", "run_daily.py",
              "run_whatsapp_brief.py"]

PASS = []


def ok(name, cond):
    if not cond:
        raise AssertionError(name)
    PASS.append(name)


def _py_files():
    files = []
    for d in SCAN_DIRS:
        p = os.path.join(ROOT, d)
        if os.path.isdir(p):
            files += [os.path.join(p, f) for f in sorted(os.listdir(p)) if f.endswith(".py")]
    for f in SCAN_FILES:
        fp = os.path.join(ROOT, f)
        if os.path.exists(fp):
            files.append(fp)
    return files


def _offenders():
    hits = []
    for fp in _py_files():
        with open(fp, encoding="utf-8") as fh:
            for i, line in enumerate(fh, 1):
                if BARE.search(line):
                    hits.append(f"{os.path.relpath(fp, ROOT)}:{i}: {line.strip()}")
    return hits


def test_engine_code_has_no_bare_llm_param_literals():
    hits = _offenders()
    ok("scanned_some_files", len(_py_files()) >= 5)
    ok("no_bare_llm_params [" + ("; ".join(hits) if hits else "clean") + "]", not hits)


def test_detector_actually_catches_the_pattern():
    # If the detector can't catch the very thing it guards, the green above is hollow.
    ok("flags_temperature_literal", bool(BARE.search("resp = completion(model=m, temperature=0.5)")))
    ok("flags_max_tokens_literal", bool(BARE.search("completion(model=m, max_tokens=4500)")))
    ok("flags_signed_literal", bool(BARE.search("completion(top_p=-1)")))


def test_detector_allows_config_driven_and_variables():
    ok("allows_config_get_default", not BARE.search('completion(temperature=float(config.get("x", 0.3)))'))
    ok("allows_variable", not BARE.search("completion(temperature=temp, max_tokens=mt)"))
    ok("ignores_substring_key", not BARE.search('config.get("whatsapp_temperature", 0.3)'))


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
