"""Resilient LLM calling — hard timeout + provider fallback + a sticky per-run circuit breaker.

WHY (2026-06-22 incident): Gemini became unreachable from the host. The Gemini-only stages
(classifier, deduplicator embeddings, title-dedup, analyst, sequencing) had NO request timeout
and NO fallback, so every call HUNG — litellm's own `timeout=` did not bound a TCP-connect hang
("Connection timed out after None seconds" still took 84s). The classifier thrashed 63 minutes,
the analyst scored 0, the writer had nothing -> no brief, and the WhatsApp run hung until killed.

This module makes every LLM call:
  1. HARD-bounded by a wall-clock timeout (run in a daemon thread we abandon if it overruns) — a
     hung provider fails FAST instead of blocking the whole pipeline;
  2. fall back to a secondary model (e.g. Anthropic Haiku when Gemini is down) — the same idea the
     writer already uses, extended to the cheap stages that had none;
  3. trip a STICKY breaker after N consecutive primary failures, so we don't pay the timeout on
     every call for the rest of the run — we switch straight to the fallback.

Injectable + pure-ish: `completion_fn` is passed in (defaults to litellm.completion) so tests
drive it with fakes (hang / raise / succeed) without network. Config-driven; defaults PRESERVE
behaviour — the fallback only fires when the primary FAILS, so a healthy run is byte-for-byte
unchanged (same model, same output).
"""
import threading


class LLMTimeout(Exception):
    """Raised when a bounded LLM call overruns its wall-clock budget."""


def call_bounded(fn, timeout_s):
    """Run fn() in a daemon thread; return its result, or raise LLMTimeout if it does not finish
    within timeout_s. An overrunning thread is abandoned (Python can't kill a thread) but the
    CALLER is freed immediately — this is the hard bound litellm's own timeout failed to provide.
    A real exception from fn() is re-raised to the caller unchanged."""
    box = {}

    def _run():
        try:
            box["v"] = fn()
        except BaseException as e:  # noqa: BLE001 — relay any provider error to the caller
            box["e"] = e

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout_s)
    if t.is_alive():
        raise LLMTimeout(f"LLM call exceeded {timeout_s}s wall-clock budget")
    if "e" in box:
        raise box["e"]
    return box.get("v")


class ResilientLLM:
    """A primary model with an optional fallback, a hard per-call timeout, and a sticky breaker.

    .complete(messages, **kw) -> (response, used_model). The fallback is only used when the
    primary fails, so a healthy run never touches it. Once `breaker_threshold` CONSECUTIVE primary
    failures occur, the breaker opens and all further calls go straight to the fallback (no more
    paying the dead primary's timeout). The breaker stays open for the run (an outage rarely
    un-breaks mid-run; sticky avoids thrashing)."""

    def __init__(self, primary, fallback=None, timeout_s=60, breaker_threshold=3,
                 completion_fn=None, label="llm"):
        self.primary = primary
        self.fallback = fallback if (fallback and fallback != primary) else None
        self.timeout_s = float(timeout_s)
        self.breaker_threshold = max(1, int(breaker_threshold))
        self._completion = completion_fn
        self.label = label
        self._consec_fail = 0
        self.breaker_open = False
        self.used_fallback = False

    def _completion_fn(self):
        if self._completion is not None:
            return self._completion
        from litellm import completion
        return completion

    def effective_model(self):
        """The model that produced (most of) this run's output — the fallback once the breaker
        opened, else the primary. Used for cost/model logging."""
        return self.fallback if (self.breaker_open and self.fallback) else self.primary

    def _raw(self, model, messages, kwargs):
        fn = self._completion_fn()
        kw = dict(kwargs)
        kw.setdefault("timeout", self.timeout_s)   # best-effort provider-side bound
        kw.setdefault("num_retries", 0)            # our breaker/fallback replaces litellm's retries
        return call_bounded(lambda: fn(model=model, messages=messages, **kw), self.timeout_s)

    def complete(self, messages, **kwargs):
        """Return (response, used_model). Hard-bounded; falls back on failure; trips the breaker."""
        if self.breaker_open and self.fallback:          # breaker open -> skip the dead primary
            self.used_fallback = True
            return self._raw(self.fallback, messages, kwargs), self.fallback
        try:
            resp = self._raw(self.primary, messages, kwargs)
            self._consec_fail = 0
            return resp, self.primary
        except Exception as e:
            self._consec_fail += 1
            if self._consec_fail >= self.breaker_threshold and self.fallback and not self.breaker_open:
                self.breaker_open = True
                print(f"  [{self.label}] primary {self.primary} failed {self._consec_fail}x "
                      f"({type(e).__name__}: {str(e)[:80]}) — switching to fallback "
                      f"{self.fallback} for the rest of the run.")
            if self.fallback:
                self.used_fallback = True
                return self._raw(self.fallback, messages, kwargs), self.fallback
            raise


def resilient_from_config(config, primary_key, fallback_key, default_primary,
                          default_fallback="anthropic/claude-haiku-4-5", label="llm",
                          completion_fn=None):
    """Build a ResilientLLM from config. The fallback only fires on a primary FAILURE, so a healthy
    run is unchanged. Set the fallback key to '' / null to disable fallback (a primary failure then
    raises as before — but the call is still HARD-bounded so it can never hang)."""
    fallback = config.get(fallback_key, default_fallback)
    return ResilientLLM(
        primary=config.get(primary_key, default_primary),
        fallback=fallback or None,
        timeout_s=float(config.get("llm_request_timeout_seconds", 60)),
        breaker_threshold=int(config.get("llm_breaker_threshold", 3)),
        completion_fn=completion_fn, label=label,
    )


def embed_bounded(embedding_fn, model, inputs, timeout_s, **kwargs):
    """Hard-bounded embedding call (no fallback — Anthropic has no embeddings; the deduplicator
    skips clustering gracefully on persistent failure). Raises LLMTimeout on a hang."""
    return call_bounded(lambda: embedding_fn(model=model, input=inputs, **kwargs), timeout_s)
