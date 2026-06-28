"""
Writer-on-subscription seam (Phase 2 cost move).

Run the writer's draft via HEADLESS Claude Code (`claude -p`) on the flat Max subscription instead of
the metered Anthropic API. The subscription quota is reachable ONLY this way — direct SDK / API-key
calls always bill the API. Behaviour-preserving: same system + user prompt in, the same briefing text
out. The caller (writer.run_writer) falls back to the API/litellm path on ANY failure here, so a run
never silently drops.

To keep this clean + cheap on quota we strip Claude Code's coding context: replace the default system
prompt with the writer's, exclude the dynamic system-prompt sections, run in a NEUTRAL cwd (so no
project CLAUDE.md is loaded), and read the (large) user prompt from stdin. Only the writer stage moves;
the high-volume analyst stays on the API.
"""
import json
import os
import subprocess
import tempfile


def parse_cc_json(stdout):
    """Parse a `claude -p --output-format json` payload -> (text, model_used, tokens_in, tokens_out).
    Raises on an error/empty result. Pure (no subprocess) so it is unit-testable."""
    data = json.loads(stdout)
    if not isinstance(data, dict):
        raise RuntimeError("claude -p: non-object json")
    if data.get("is_error") or data.get("subtype") != "success":
        raise RuntimeError(f"claude -p error: {str(data)[:300]}")
    text = (data.get("result") or "").strip()
    if not text:
        raise RuntimeError("claude -p returned empty result")
    usage = data.get("usage") or {}
    t_in = (int(usage.get("input_tokens", 0) or 0)
            + int(usage.get("cache_creation_input_tokens", 0) or 0)
            + int(usage.get("cache_read_input_tokens", 0) or 0))
    t_out = int(usage.get("output_tokens", 0) or 0)
    model_used = "subscription:claude-code"
    mu = data.get("modelUsage") or {}
    if mu:
        model_used = "subscription:" + next(iter(mu.keys()))
    return text, model_used, t_in, t_out


def complete_via_subscription(system_prompt, user_prompt, model="sonnet", timeout=600, cli="claude",
                              max_thinking_tokens=0):
    """Run system + user through `claude -p` on the subscription. Returns
    (text, model_used, tokens_in, tokens_out). Raises on any failure (caller falls back to the API).

    max_thinking_tokens=0 DISABLES Claude Code's default extended thinking — without this the headless
    call loops/hangs (>600s) on the big constrained brief synthesis; with it, ~70s. This is the load-
    bearing fix that makes the subscription path actually complete in the writer run."""
    # Debug hook (env-gated, off in production): dump the EXACT prompt this run would send, then skip
    # the live call so the run falls back fast. Used to reproduce a hang in isolation.
    _dump = os.getenv("NEWSFRAMER_CC_DUMP")
    if _dump:
        os.makedirs(_dump, exist_ok=True)
        with open(os.path.join(_dump, "sys.txt"), "w", encoding="utf-8") as _f:
            _f.write(system_prompt)
        with open(os.path.join(_dump, "usr.txt"), "w", encoding="utf-8") as _f:
            _f.write(user_prompt)
        raise RuntimeError("NEWSFRAMER_CC_DUMP set: dumped prompt, skipped live call (debug)")
    # `claude -p` is an AGENT (multi-turn, tool-capable): on a big writer prompt it loops/hangs. Force a
    # SINGLE-SHOT generation (--max-turns 1) and disable every tool so it can only emit the briefing.
    # --disallowed-tools is variadic, so it MUST be the last flag (it consumes the trailing tool names).
    args = [
        cli, "-p", "--output-format", "json",
        "--system-prompt", system_prompt,          # REPLACE the coding-agent default with the writer's
        "--model", str(model),
        "--exclude-dynamic-system-prompt-sections",  # drop dynamic CC context to cut quota overhead
        "--max-turns", "1",                          # one generation, no agentic looping
        "--disallowed-tools", "Bash", "Read", "Edit", "Write", "Glob", "Grep",
        "WebFetch", "WebSearch", "Task", "TodoWrite", "NotebookEdit",
    ]
    # Feed the (large) user prompt via a temp FILE redirected to stdin — NOT subprocess input=. On
    # Windows, input=<large str> deadlocks the node CLI (a ~14KB prompt that returns in ~12s via a shell
    # pipe hangs past the timeout via input=); a real file handle behaves like the shell `< file`.
    fd, path = tempfile.mkstemp(suffix=".txt")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(user_prompt)
        env = {**os.environ, "MAX_THINKING_TOKENS": str(int(max_thinking_tokens))}
        with open(path, "rb") as stdin_f:
            proc = subprocess.run(
                args, stdin=stdin_f, capture_output=True, text=True,
                timeout=timeout, cwd=tempfile.gettempdir(), encoding="utf-8", env=env,
            )
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    if proc.returncode != 0:
        raise RuntimeError(f"claude -p rc={proc.returncode}: {(proc.stderr or '')[-300:]}")
    return parse_cc_json(proc.stdout)
