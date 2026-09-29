"""
Writer-on-subscription seam (Phase 2 cost move).

Run the writer's draft via HEADLESS Claude Code (`claude -p`) on the flat Max subscription instead of
the metered Anthropic API. The subscription quota is reachable ONLY this way — direct SDK / API-key
calls always bill the API. Behaviour-preserving: same system + user prompt in, the same briefing text
out. The caller (writer.run_writer) falls back to the API/litellm path on ANY failure here, so a run
never silently drops.

To keep this clean + cheap on quota we strip Claude Code's coding context: replace the default system
prompt with the writer's, exclude the dynamic system-prompt sections, run in a NEUTRAL cwd (so no
project CLAUDE.md is loaded), and read the (large) user prompt from stdin.

Every LLM stage can use it (`use_subscription` in config/models.yaml, overridable per stage with
`<stage>_use_subscription`). When a subscription call fails, the stage falls back to its API model
(only if you configured an API key for it) and `notify_fallback` tells you, loudly, by default.
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


# --- Shared subscription routing for every stage -------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_NOTIFIED = set()


def use_subscription(config, stage):
    """True if `stage` should try the Claude subscription first. Per-stage key wins, else the global
    `use_subscription` key, else False."""
    v = (config or {}).get(f"{stage}_use_subscription")
    if v is None:
        v = (config or {}).get("use_subscription", False)
    return bool(v)


def subscription_settings(config, stage):
    c = config or {}
    return {
        "model": c.get(f"{stage}_subscription_model", c.get("subscription_model", "haiku")),
        "timeout": int(c.get(f"{stage}_subscription_timeout_seconds", c.get("subscription_timeout_seconds", 600))),
        "max_thinking_tokens": int(c.get(f"{stage}_subscription_max_thinking_tokens", 0)),
    }


def notify_fallback(stage, err, config=None):
    """The subscription was NOT used for a call: say so loudly. Every occurrence is printed and
    appended to logs/subscription-fallback.log; the first one per stage per run is also sent as an
    alert (Telegram alert bot if configured) unless notify_on_subscription_fallback is false."""
    msg = (f"NewsFramer: the Claude subscription was not used for stage '{stage}' "
           f"({type(err).__name__}: {str(err)[:160]}). The API fallback model runs instead, "
           f"if you configured one; otherwise this call fails.")
    print(f"  !! {msg}")
    try:
        import time as _t
        if os.getenv("NEWSFRAMER_NO_ALERTS") and BASE_DIR == os.path.dirname(os.path.dirname(os.path.abspath(__file__))):
            raise RuntimeError("test run: no log write into the real repo")
        os.makedirs(os.path.join(BASE_DIR, "logs"), exist_ok=True)
        with open(os.path.join(BASE_DIR, "logs", "subscription-fallback.log"), "a", encoding="utf-8") as f:
            f.write(f"{_t.strftime('%Y-%m-%d %H:%M:%S')}\t{stage}\t{type(err).__name__}: {str(err)[:300]}\n")
    except Exception:
        pass
    if stage in _NOTIFIED or not bool((config or {}).get("notify_on_subscription_fallback", True)):
        return
    if os.getenv("NEWSFRAMER_NO_ALERTS"):   # set by the test suite: never message a real phone from a test
        return
    _NOTIFIED.add(stage)
    try:
        try:
            import deliver
        except ImportError:
            from agents import deliver
        deliver.send_alert("⚠ " + msg)
    except Exception as e:
        print(f"  (fallback alert not sent: {type(e).__name__})")


class _SubMsg:
    def __init__(self, content): self.message = type("M", (), {"content": content})()


class _SubUsage:
    def __init__(self, t_in, t_out):
        self.prompt_tokens = t_in
        self.completion_tokens = t_out


class _SubResponse:
    """Mimics the litellm response shape callers read (choices[0].message.content + usage)."""
    def __init__(self, content, t_in, t_out):
        self.choices = [_SubMsg(content)]
        self.usage = _SubUsage(t_in, t_out)


def _split_messages(messages):
    system = "\n\n".join(m["content"] for m in messages if m.get("role") == "system")
    user = "\n\n".join(m["content"] for m in messages if m.get("role") == "user")
    return system, user


class SubscriptionLLM:
    """Wraps an API ResilientLLM: `claude -p` first, the API llm on ANY failure (notified). Same
    .complete(messages, **kw) -> (response, used) surface and the proxy attributes callers read."""
    def __init__(self, api_llm, model="haiku", timeout=600, max_thinking_tokens=0, stage="llm", config=None):
        self.api = api_llm
        self.model = model
        self.timeout = int(timeout)
        self.max_thinking_tokens = int(max_thinking_tokens)
        self.stage = stage
        self.config = config
        self.used_subscription = False
        self.used_api_fallback = False

    def complete(self, messages, **kwargs):
        system, user = _split_messages(messages)
        try:
            text, _model_used, t_in, t_out = complete_via_subscription(
                system, user, model=self.model, timeout=self.timeout,
                max_thinking_tokens=self.max_thinking_tokens)
            self.used_subscription = True
            return _SubResponse(text, t_in, t_out), "subscription"
        except Exception as e:
            self.used_api_fallback = True
            notify_fallback(self.stage, e, self.config)
            return self.api.complete(messages, **kwargs)

    @property
    def fallback(self):
        return self.api.fallback

    @property
    def timeout_s(self):
        return self.api.timeout_s

    @property
    def used_fallback(self):
        return bool(getattr(self.api, "used_fallback", False) or self.used_api_fallback)

    def effective_model(self):
        # An API fallback (even once) overrides; `subscription:` makes cost logging record $0.
        if self.used_api_fallback:
            return self.api.effective_model()
        return f"subscription:{self.model}"


def maybe_wrap(api_llm, config, stage):
    """Wrap a ResilientLLM in SubscriptionLLM when `stage` uses the subscription; else unchanged."""
    if not use_subscription(config, stage):
        return api_llm
    st = subscription_settings(config, stage)
    return SubscriptionLLM(api_llm, model=st["model"], timeout=st["timeout"],
                           max_thinking_tokens=st["max_thinking_tokens"], stage=stage, config=config)


def completion_fn(config, stage, api_completion=None):
    """A litellm-style completion(model=, messages=, **kw) that tries the subscription first and
    calls the API model on failure (notified). Returns plain api_completion when the stage is off."""
    if api_completion is None:
        from litellm import completion as api_completion
    if not use_subscription(config, stage):
        return api_completion
    st = subscription_settings(config, stage)

    def _fn(model=None, messages=None, **kw):
        system, user = _split_messages(messages or [])
        try:
            text, _m, t_in, t_out = complete_via_subscription(
                system, user, model=st["model"], timeout=st["timeout"],
                max_thinking_tokens=st["max_thinking_tokens"])
            return _SubResponse(text, t_in, t_out)
        except Exception as e:
            notify_fallback(stage, e, config)
            return api_completion(model=model, messages=messages, **kw)
    return _fn
