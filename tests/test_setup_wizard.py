"""
Tests for setup_wizard.py — the guided first-run setup that asks for the operator's keys
conversationally and writes `.env` itself (the near-zero-effort setup path for reusers).

Contract:
  - build_env_content (pure): renders KEY=value lines for answered vars, required first,
    omits optionals left blank, no value ever altered.
  - run_wizard: writes .env into the given base_dir (dependency-injected — tests run in a
    tempdir, never near the real repo .env); a REQUIRED var re-asks until non-empty; an
    optional var may be skipped with Enter.
  - Safety: an EXISTING .env is NEVER touched — the wizard refuses and exits non-zero.
  - Secrecy: entered values are never echoed back in the wizard's own output (names only).

    venv\\Scripts\\python.exe tests\\test_setup_wizard.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import setup_wizard as sw  # noqa: E402

PASS = []


def ok(name, cond):
    if not cond:
        raise AssertionError(name)
    PASS.append(name)


ANSWERS = {
    "SUPABASE_URL": "https://abcd1234.supabase.co",
    "SUPABASE_SERVICE_KEY": "fake-service-key-value-000",
    "GEMINI_API_KEY": "fake-gemini-key-111",
    "TELEGRAM_BOT_TOKEN": "1234567890:fake-token-222",
    "TELEGRAM_CHAT_ID": "246813579",  # deliberately NOT a substring of any wizard hint text
}


def scripted(seq):
    """input_fn that pops answers in order."""
    it = iter(seq)

    def _fn(prompt=""):
        return next(it)
    return _fn


def full_input_sequence(optionals=("", "", "")):
    """Answers for the 5 required (in sw.REQUIRED order) then the optionals."""
    return [ANSWERS[name] for name, _hint in sw.REQUIRED] + list(optionals)


def test_build_env_content_renders_and_omits_blanks():
    content = sw.build_env_content({**ANSWERS, "ANTHROPIC_API_KEY": ""})
    for k, v in ANSWERS.items():
        ok(f"content_has_{k}", f"{k}={v}" in content)
    ok("blank_optional_omitted", "ANTHROPIC_API_KEY" not in content)
    ok("ends_with_newline", content.endswith("\n"))


def test_wizard_writes_env_in_base_dir():
    with tempfile.TemporaryDirectory() as d:
        out = []
        rc = sw.run_wizard(base_dir=d, input_fn=scripted(full_input_sequence()),
                           print_fn=out.append)
        env_path = os.path.join(d, ".env")
        ok("wizard_rc_0", rc == 0)
        ok("wizard_env_exists", os.path.exists(env_path))
        with open(env_path, encoding="utf-8") as f:
            content = f.read()
        for k, v in ANSWERS.items():
            ok(f"env_has_{k}", f"{k}={v}" in content)


def test_required_reasks_until_nonempty():
    with tempfile.TemporaryDirectory() as d:
        seq = ["", ""] + full_input_sequence()  # two blank tries at the first required var
        rc = sw.run_wizard(base_dir=d, input_fn=scripted(seq), print_fn=lambda s: None)
        ok("reask_rc_0", rc == 0)
        with open(os.path.join(d, ".env"), encoding="utf-8") as f:
            ok("reask_first_var_present", f"SUPABASE_URL={ANSWERS['SUPABASE_URL']}" in f.read())


def test_optional_skipped_with_enter():
    with tempfile.TemporaryDirectory() as d:
        sw.run_wizard(base_dir=d, input_fn=scripted(full_input_sequence(("", "", ""))),
                      print_fn=lambda s: None)
        with open(os.path.join(d, ".env"), encoding="utf-8") as f:
            content = f.read()
        ok("optional_absent", "ANTHROPIC_API_KEY" not in content and "FIRECRAWL_API_KEY" not in content)


def test_existing_env_is_never_touched():
    with tempfile.TemporaryDirectory() as d:
        env_path = os.path.join(d, ".env")
        with open(env_path, "w", encoding="utf-8") as f:
            f.write("PRECIOUS=do-not-touch\n")
        out = []
        rc = sw.run_wizard(base_dir=d, input_fn=scripted(full_input_sequence()),
                           print_fn=out.append)
        with open(env_path, encoding="utf-8") as f:
            after = f.read()
        ok("existing_refused_rc", rc != 0)
        ok("existing_unchanged", after == "PRECIOUS=do-not-touch\n")
        ok("existing_message", any(".env" in str(line) for line in out))


def test_values_never_echoed_in_output():
    with tempfile.TemporaryDirectory() as d:
        out = []
        sw.run_wizard(base_dir=d,
                      input_fn=scripted(full_input_sequence(("opt-anthropic-999", "", ""))),
                      print_fn=out.append)
        blob = "\n".join(str(line) for line in out)
        for v in list(ANSWERS.values()) + ["opt-anthropic-999"]:
            ok(f"not_echoed_{v[:12]}", v not in blob)


def test_bad_supabase_url_warns_but_writes():
    with tempfile.TemporaryDirectory() as d:
        seq = full_input_sequence()
        seq[0] = "notaurl"
        out = []
        rc = sw.run_wizard(base_dir=d, input_fn=scripted(seq), print_fn=out.append)
        ok("warn_rc_0", rc == 0)
        blob = "\n".join(str(line) for line in out).lower()
        ok("warn_printed", "warn" in blob or "unusual" in blob or "look" in blob)
        with open(os.path.join(d, ".env"), encoding="utf-8") as f:
            ok("warn_still_written", "SUPABASE_URL=notaurl" in f.read())


def main():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print(f"{len(PASS)} checks passed, 0 test(s) failed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
