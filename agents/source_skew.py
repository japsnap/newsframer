"""
NF-D3 — source-skew warning (log-only).

Now that NF-D1 seeded Ground-News bias on the sources, this flags a brief theme that leans
hard one way with NO counter-voice: among a theme's DISTINCT sources that carry a known lean,
the opposing lean is absent and >= skew_ratio of them are the one side. Center is neutral and
dilutes the skew (a centrist source counts toward the total). One vote per source.

PURE detection — it never changes the brief, never raises on odd input. The Writer just prints
the warning to the run log (like the NF-F2 char-overrun flag), so editorial bias is VISIBLE
without altering what's delivered.
"""


def _norm(raw):
    """Ground-News bias label -> 'left' | 'center' | 'right' | None (None = unknown/unseeded)."""
    if not raw:
        return None
    s = str(raw).strip().lower()
    if "left" in s:
        return "left"
    if "right" in s:
        return "right"
    if "cent" in s or "middle" in s:
        return "center"
    return None


def coverage_note(source_biases):
    """One-sided-coverage note for a single story/theme (stricter than skew_warning, used for
    the user-facing 'left/right media only' line). One vote per DISTINCT source:
      - every known-lean source is left  -> 'left'  ("left media only" — no center, no right),
      - every known-lean source is right -> 'right',
      - any center source, both sides, or no placed source -> None.
    Pure; tolerant of malformed items."""
    by_source = {}
    for item in (source_biases or []):
        try:
            sid, bias = item
        except (ValueError, TypeError):
            continue
        if sid not in by_source:
            by_source[sid] = _norm(bias)
    placed = {v for v in by_source.values() if v}
    if placed == {"left"}:
        return "left"
    if placed == {"right"}:
        return "right"
    return None


def skew_warning(source_biases, min_sources=3, skew_ratio=0.75):
    """source_biases: iterable of (source_id, raw_bias_label) for a theme's articles.

    Returns a one-line warning string when the theme is source-skewed, else None:
      - count one vote per DISTINCT source (a source repeated across articles counts once),
      - keep only sources with a KNOWN lean (left/center/right); need >= min_sources of them,
      - if both Left AND Right are present -> balanced -> None,
      - else if one lean reaches >= skew_ratio of the placed sources and the opposing lean is
        absent -> warn (center dilutes: it's in the denominator but never a 'side').
    Pure; tolerant of malformed items (skipped, never raises)."""
    by_source = {}
    for item in (source_biases or []):
        try:
            sid, bias = item
        except (ValueError, TypeError):
            continue
        if sid not in by_source:
            by_source[sid] = _norm(bias)
    placed = [v for v in by_source.values() if v]
    n = len(placed)
    if n < min_sources:
        return None
    left, right = placed.count("left"), placed.count("right")
    if left and right:
        return None
    if right == 0 and left >= skew_ratio * n:
        return f"skewed Left ({left}/{n} placed sources, no Right voice)"
    if left == 0 and right >= skew_ratio * n:
        return f"skewed Right ({right}/{n} placed sources, no Left voice)"
    return None
