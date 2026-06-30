"""
Tests for the analyst BATCH path (NF-ANALYST-BATCH). The analyst used to make ONE LLM
call per article, re-sending the interests/hypotheses context each time (~150 calls/run).
Batching sends the context ~15x instead of ~150x. These tests pin the deterministic seams:
  - build_batch_user_prompt  : every article (id + title) is in the prompt; asks for an ARRAY
  - BATCH_INSTRUCTION        : the batch-mode system instruction (config-overridable default)
  - map_batch_results        : pure mapping by article_id, drops hallucinated/duplicate ids,
                               reports the articles the LLM omitted (so they can be retried,
                               never silently dropped)
  - analyze_batch            : parses a litellm-shaped array reply + sums tokens (fake LLM)
  - resolve_batch_size       : the config knob; <=1 means "use the per-article path"

Score EQUIVALENCE (batched vs per-article) is non-deterministic LLM output and is verified
by a separate real-data, no-insert comparison harness — NOT here.

    venv\\Scripts\\python.exe tests\\test_analyst_batch.py
"""
import os
import sys
import json
import re

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
import analyst as a  # noqa: E402

PASS = []


def ok(name, cond):
    if not cond:
        raise AssertionError(name)
    PASS.append(name)


# --- Fixtures ---------------------------------------------------------------

SOURCES = {
    "src-1": {"name": "Dawn", "category": "pakistan", "publisher_bias_score": 0.0},
    "src-2": {"name": "Al Jazeera", "category": "geopolitics", "publisher_bias_score": -0.2},
}

BATCH = [
    {"id": "aaa", "source_id": "src-1", "title": "Floods displace thousands in Sindh",
     "content_raw": "Heavy monsoon rains...", "published_at": "2026-06-30T01:00:00Z", "branch": "IMMEDIATE"},
    {"id": "bbb", "source_id": "src-2", "title": "Ceasefire talks resume in Geneva",
     "content_raw": "Negotiators returned...", "published_at": "2026-06-30T02:00:00Z", "branch": "KEEP_WARM"},
    {"id": "ccc", "source_id": "src-1", "title": "Rupee steadies against dollar",
     "content_raw": "The currency held...", "published_at": "2026-06-30T03:00:00Z", "branch": "KEEP_WARM"},
]


def _score_obj(article_id, rel=7):
    return {
        "article_id": article_id,
        "relevance_score": rel,
        "label": "NEW_SIGNAL",
        "hypotheses": [],
        "topics": ["geopolitics"],
        "actionability": 1,
        "perspective_invited": True,
        "reasoning": "test",
        "differentiator": "standalone",
    }


class _Usage:
    def __init__(self, t_in, t_out):
        self.prompt_tokens = t_in
        self.completion_tokens = t_out


class _Msg:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.message = _Msg(content)


class _Resp:
    def __init__(self, content, t_in, t_out):
        self.choices = [_Choice(content)]
        self.usage = _Usage(t_in, t_out)


class FakeLLM:
    """Faithful stand-in for ResilientLLM: .complete(messages, temperature) -> (response, used).
    Response matches the litellm shape the analyst reads (choices[0].message.content + usage)."""
    def __init__(self, content, t_in=900, t_out=120):
        self._content = content
        self._t_in = t_in
        self._t_out = t_out
        self.calls = []

    def complete(self, messages, temperature=None):
        self.calls.append(messages)
        return _Resp(self._content, self._t_in, self._t_out), "primary"


# --- build_batch_user_prompt ------------------------------------------------

def test_batch_prompt_lists_every_article():
    p = a.build_batch_user_prompt(BATCH, SOURCES)
    for art in BATCH:
        ok(f"id_present_{art['id']}", art["id"] in p)
        ok(f"title_present_{art['id']}", art["title"] in p)
    ok("names_present", "Dawn" in p and "Al Jazeera" in p)


def test_batch_prompt_asks_for_array():
    p = a.build_batch_user_prompt(BATCH, SOURCES).lower()
    # Must steer the model to a JSON array keyed by article_id (not a single object).
    ok("mentions_array", "array" in p or "list" in p)
    ok("mentions_article_id", "article_id" in p)


# --- BATCH_INSTRUCTION ------------------------------------------------------

def test_batch_instruction_requires_id_and_array():
    instr = a.BATCH_INSTRUCTION.lower()
    ok("instr_array", "array" in instr)
    ok("instr_article_id", "article_id" in instr)
    ok("instr_each", "each" in instr or "one object per" in instr or "per article" in instr)


# --- map_batch_results (pure) ----------------------------------------------

def test_map_results_maps_by_id():
    parsed = [_score_obj("aaa", 8), _score_obj("bbb", 5), _score_obj("ccc", 3)]
    mapping, missing = a.map_batch_results(BATCH, parsed)
    ok("all_mapped", set(mapping.keys()) == {"aaa", "bbb", "ccc"})
    ok("none_missing", missing == [])
    ok("right_value", mapping["aaa"]["relevance_score"] == 8)


def test_map_results_drops_hallucinated_id():
    parsed = [_score_obj("aaa"), _score_obj("zzz")]  # zzz is not in the batch
    mapping, missing = a.map_batch_results(BATCH, parsed)
    ok("hallucinated_dropped", "zzz" not in mapping)
    ok("kept_real", "aaa" in mapping)
    ok("bbb_and_ccc_missing", set(missing) == {"bbb", "ccc"})


def test_map_results_drops_duplicate_id():
    parsed = [_score_obj("aaa", 7), _score_obj("aaa", 2), _score_obj("bbb", 6)]
    mapping, missing = a.map_batch_results(BATCH, parsed)
    ok("dup_first_wins", mapping["aaa"]["relevance_score"] == 7)
    ok("ccc_missing", missing == ["ccc"])


def test_map_results_reports_missing_when_short():
    parsed = [_score_obj("aaa")]
    mapping, missing = a.map_batch_results(BATCH, parsed)
    ok("only_aaa", set(mapping.keys()) == {"aaa"})
    ok("missing_two", set(missing) == {"bbb", "ccc"})


# --- analyze_batch (fake LLM, faithful shape) -------------------------------

def test_analyze_batch_parses_array_and_sums_tokens():
    content = json.dumps([_score_obj("aaa", 9), _score_obj("bbb", 4), _score_obj("ccc", 6)])
    llm = FakeLLM(content, t_in=1000, t_out=150)
    parsed, t_in, t_out = a.analyze_batch(BATCH, "CONTEXT BLOCK", SOURCES, llm)
    ok("parsed_len", len(parsed) == 3)
    ok("tokens_in", t_in == 1000)
    ok("tokens_out", t_out == 150)
    # the batch instruction + context must reach the system message
    sys_msg = llm.calls[0][0]["content"]
    ok("system_has_instruction", "article_id" in sys_msg.lower())
    ok("system_has_context", "CONTEXT BLOCK" in sys_msg)


def test_analyze_batch_coerces_single_object():
    # A model that returns ONE object instead of an array must not crash (llm_json coercion).
    content = json.dumps(_score_obj("aaa", 7))
    llm = FakeLLM(content)
    parsed, _, _ = a.analyze_batch(BATCH[:1], "CTX", SOURCES, llm)
    ok("coerced_to_list", isinstance(parsed, list) and len(parsed) == 1)


# --- resolve_batch_size (the knob) -----------------------------------------

def test_resolve_batch_size_default_is_ten():
    ok("default_10", a.resolve_batch_size({}) == 10)


def test_resolve_batch_size_one_means_per_article():
    ok("explicit_1", a.resolve_batch_size({"analyst_batch_size": 1}) == 1)
    ok("explicit_25", a.resolve_batch_size({"analyst_batch_size": 25}) == 25)
    # a junk value falls back to the default rather than crashing the run
    ok("junk_falls_back", a.resolve_batch_size({"analyst_batch_size": "oops"}) == 10)


# --- score_articles: batch + per-article fallback (the data-loss guard) -----

class RoutingFakeLLM:
    """Returns a (short) array on the batch call and a per-article object on the per-article
    fallback call, so we can prove a missing/failed article is RE-SCORED, never dropped."""
    def __init__(self, batch_returns_ids):
        self.batch_returns_ids = batch_returns_ids
        self.batch_calls = 0
        self.single_calls = 0

    def complete(self, messages, temperature=None):
        system = messages[0]["content"]
        user = messages[1]["content"]
        if "BATCH MODE" in system:
            self.batch_calls += 1
            content = json.dumps([_score_obj(i) for i in self.batch_returns_ids])
            return _Resp(content, 1000, 150), "primary"
        self.single_calls += 1
        m = re.search(r"article_id: (\S+)", user)
        aid = m.group(1) if m else "unknown"
        return _Resp(json.dumps(_score_obj(aid)), 200, 30), "primary"


class ThrowingBatchLLM(RoutingFakeLLM):
    """The batch call always fails; the per-article fallback succeeds."""
    def complete(self, messages, temperature=None):
        if "BATCH MODE" in messages[0]["content"]:
            self.batch_calls += 1
            raise RuntimeError("batch boom")
        return super().complete(messages, temperature)


def test_score_articles_scores_all_in_one_batch():
    llm = RoutingFakeLLM(batch_returns_ids=["aaa", "bbb", "ccc"])
    rows, failed, t_in, t_out = a.score_articles(BATCH, "CTX", SOURCES, set(), llm, 10)
    scored = {art["id"] for art, _ in rows}
    ok("all_three", scored == {"aaa", "bbb", "ccc"})
    ok("no_failed", failed == [])
    ok("one_batch_call", llm.batch_calls == 1)
    ok("no_single_calls", llm.single_calls == 0)
    ok("tokens", t_in == 1000 and t_out == 150)
    ok("rows_cleaned", all("relevance_score" in cleaned for _, cleaned in rows))


def test_score_articles_retries_missing_per_article():
    # The batch reply omits bbb + ccc -> they must be re-scored individually, not lost.
    llm = RoutingFakeLLM(batch_returns_ids=["aaa"])
    rows, failed, t_in, t_out = a.score_articles(BATCH, "CTX", SOURCES, set(), llm, 10)
    scored = {art["id"] for art, _ in rows}
    ok("all_recovered", scored == {"aaa", "bbb", "ccc"})
    ok("no_failed", failed == [])
    ok("two_single_calls", llm.single_calls == 2)
    ok("tokens_summed", t_in == 1000 + 200 + 200)


def test_score_articles_whole_chunk_fallback_on_batch_error():
    # A failed batch call must fall back to per-article for the WHOLE chunk (no 10-article loss).
    saved = (a.MAX_RETRIES, a.RETRY_BACKOFF_SECONDS)
    a.MAX_RETRIES, a.RETRY_BACKOFF_SECONDS = 1, 0  # keep the retry loop fast in-test
    try:
        llm = ThrowingBatchLLM(batch_returns_ids=[])
        rows, failed, _, _ = a.score_articles(BATCH, "CTX", SOURCES, set(), llm, 10)
    finally:
        a.MAX_RETRIES, a.RETRY_BACKOFF_SECONDS = saved
    scored = {art["id"] for art, _ in rows}
    ok("all_via_fallback", scored == {"aaa", "bbb", "ccc"})
    ok("three_single_calls", llm.single_calls == 3)
    ok("no_failed", failed == [])


def test_score_articles_counts_unrecoverable_as_failed():
    # If BOTH the batch and the per-article retry fail, the article is reported failed (loud),
    # not silently scored. Here every call raises.
    saved = (a.MAX_RETRIES, a.RETRY_BACKOFF_SECONDS)
    a.MAX_RETRIES, a.RETRY_BACKOFF_SECONDS = 1, 0
    try:
        class AllFail:
            def complete(self, messages, temperature=None):
                raise RuntimeError("everything is down")
        rows, failed, _, _ = a.score_articles(BATCH, "CTX", SOURCES, set(), AllFail(), 10)
    finally:
        a.MAX_RETRIES, a.RETRY_BACKOFF_SECONDS = saved
    ok("nothing_scored", rows == [])
    ok("all_failed", set(failed) == {"aaa", "bbb", "ccc"})


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
