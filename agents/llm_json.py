"""
Robust extraction of JSON from LLM responses (shared by classifier + analyst).

LLMs (Gemini Flash-Lite, Claude Haiku) drift on output SHAPE: they wrap JSON in
markdown fences, add a "Here is the JSON:" preamble or a trailing note, return a
single object where an array was requested (or a 1-item array where an object was
requested), or occasionally emit a bare string / null. The 2026-06-11 classifier
incident was exactly this: a one-article batch came back as a bare object, the
code iterated it as a list, got dict KEYS (strings), and crashed on
'str' object has no attribute 'get'.

These helpers coerce whatever comes back into the shape the caller needs so a
shape slip degrades to "skip this item" instead of crashing the pipeline.
"""
import json
import re

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


def _strip_to_json(raw):
    """Return the substring most likely to be the JSON payload.

    Handles ```json fences located anywhere (not just anchored at the ends) and
    leading/trailing prose, by slicing from the first opening bracket/brace to
    the matching last closing one.
    """
    if raw is None:
        raise ValueError("empty LLM response")
    s = raw.strip()
    fence = _FENCE_RE.search(s)
    if fence:
        s = fence.group(1).strip()
    starts = [i for i in (s.find("["), s.find("{")) if i != -1]
    if starts:
        start = min(starts)
        end = max(s.rfind("]"), s.rfind("}"))
        if end > start:
            s = s[start:end + 1]
    return s.strip()


def parse_json(raw):
    """Parse an LLM response into a Python object, tolerating fences/prose.

    Raises json.JSONDecodeError on genuinely malformed JSON (callers already
    handle that), or ValueError on a None response.
    """
    return json.loads(_strip_to_json(raw))


def parse_json_list(raw):
    """Always return a list of dicts. Non-dict elements are dropped.

    - array of objects        -> objects only
    - single object           -> [object]   (the 2026-06-11 bug)
    - string / number / null  -> []          (caller treats as 'no results')
    """
    parsed = parse_json(raw)
    if isinstance(parsed, dict):
        return [parsed]
    if isinstance(parsed, list):
        return [x for x in parsed if isinstance(x, dict)]
    return []


def parse_json_obj(raw):
    """Always return a single dict.

    - object                  -> as-is
    - array                   -> first dict element (LLM returned a 1-item array)
    - anything else / no dict -> raise ValueError (lets the caller's retry run)
    """
    parsed = parse_json(raw)
    if isinstance(parsed, dict):
        return parsed
    if isinstance(parsed, list):
        for x in parsed:
            if isinstance(x, dict):
                return x
    raise ValueError(f"expected a JSON object, got {type(parsed).__name__}")
