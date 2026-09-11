"""
Critic (spec §10.13 / backlog NF-F1) — pre-send quality check on a finished brief.

Reports findings by severity (Critical / Important / Minor) and NEVER patches — it
only describes problems for a human to judge. This is the deterministic v1: cheap,
LLM-free structural checks (empties, missing citations, character overrun, thin
themes). It is designed to run between the Writer and delivery; for now it is a
STANDALONE module — NOT wired into the live send path — so it cannot affect
delivery until deliberately enabled.

    venv\\Scripts\\python.exe tests\\test_critic.py
"""
import os
import re

import yaml


def _load_config():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(base_dir, "config", "models.yaml"), "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


try:  # wrapped so a missing/broken config can't break import
    _CFG = _load_config() or {}
except Exception:
    _CFG = {}

_SEV = list(_CFG.get("critic_severity_labels", ["Critical", "Important", "Minor"]))
if len(_SEV) != 3:  # malformed override -> fall back to the defaults
    _SEV = ["Critical", "Important", "Minor"]
CRITICAL, IMPORTANT, MINOR = _SEV[0], _SEV[1], _SEV[2]
_ORDER = {CRITICAL: 3, IMPORTANT: 2, MINOR: 1}

# '## ' headings that are not themes, so the theme-count check stays fair.
_NON_THEME = tuple(_CFG.get("critic_non_theme_sections", ("highlights", "investigations")))
_LINK = re.compile(r"\]\(https?://")        # a markdown [text](http...) citation
_H2 = re.compile(r"^##\s+(.*)$", re.MULTILINE)

# --- Currency / totals checks (2026-09-08 Japan-theme bug: yen figures rendered as $,
# ~15x too big, plus a theme total that didn't match the sum of its own components). ---
_DOLLAR_ANY = re.compile(r"\$\s?[\d,]+(?:\.\d+)?\s*(?:million|billion|thousand|[MBK])?", re.IGNORECASE)
_AMOUNT_RE = r"\$\s?([\d,]+(?:\.\d+)?)\s*(billion|bn|million|mn|thousand|k|b|m)?\b"
_AMOUNT = re.compile(_AMOUNT_RE, re.IGNORECASE)
_TOTAL_AMOUNT = re.compile(
    r"(?:total(?:ing|ed|s)?|combined|altogether|collectively)\D{0,30}?" + _AMOUNT_RE, re.IGNORECASE)
_CITE_URL = re.compile(r"\((https?://[^)\s]+)\)")
_YEN_URL = re.compile(r"(?:^|[\W_])(?:yen|円)(?:$|[\W_])", re.IGNORECASE)


def _amount_to_millions(value_str, unit):
    """Normalize a '$X <unit>' match to millions-of-dollars, or None when the figure has
    no recognizable magnitude unit (so a stray '$5' can't be mistaken for a funding
    component)."""
    try:
        v = float(str(value_str).replace(",", ""))
    except (TypeError, ValueError):
        return None
    unit = (unit or "").strip().lower()
    if unit in ("billion", "bn", "b"):
        return v * 1000
    if unit in ("million", "mn", "m"):
        return v
    if unit in ("thousand", "k"):
        return v / 1000
    return None


def find_currency_mismatches(text):
    """A '$' amount stated inside a theme whose OWN citation list links to a
    yen-denominated source ('yen' in the URL slug, or '円') is a red flag for a naive
    yen->dollar mis-conversion — the Writer must carry non-USD amounts in their ORIGINAL
    currency and never invent a conversion rate. Returns [{"theme", "yen_urls"}, ...].
    Pure; never rewrites — a check that flags beats one that silently mangles numbers."""
    out = []
    for title, body in _sections(text or ""):
        if not _is_theme(title):
            continue
        yen_urls = [u for u in _CITE_URL.findall(body) if _YEN_URL.search(u)]
        if yen_urls and _DOLLAR_ANY.search(body):
            out.append({"theme": title, "yen_urls": yen_urls})
    return out


def find_theme_total_mismatches(text, tolerance_pct=0.05):
    """A theme that states a combined/total dollar figure must equal the sum of the
    dollar amounts it actually lists as components — no invented rounding, and no folding
    a lifetime cumulative total into what should be a one-period tally. Returns
    [{"theme", "stated_millions", "component_sum_millions", "diff_pct"}, ...] for any
    theme whose stated total is off from its own component sum by more than
    tolerance_pct (default 5%). Pure; never rewrites."""
    out = []
    for title, body in _sections(text or ""):
        if not _is_theme(title):
            continue
        m = _TOTAL_AMOUNT.search(body)
        if not m:
            continue
        stated = _amount_to_millions(m.group(1), m.group(2))
        if stated is None or stated <= 0:
            continue
        total_span = m.span()
        components = [
            _amount_to_millions(am.group(1), am.group(2))
            for am in _AMOUNT.finditer(body)
            if not (am.start() >= total_span[0] and am.end() <= total_span[1])
        ]
        components = [c for c in components if c is not None]
        if not components:
            continue
        comp_sum = sum(components)
        if comp_sum <= 0:
            continue
        diff_pct = abs(comp_sum - stated) / stated
        if diff_pct > tolerance_pct:
            out.append({
                "theme": title, "stated_millions": stated,
                "component_sum_millions": round(comp_sum, 3), "diff_pct": round(diff_pct * 100, 1),
            })
    return out


def _sections(text):
    """[(title, body), ...] for each '## ' section, in document order."""
    out = []
    matches = list(_H2.finditer(text or ""))
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        out.append((m.group(1).strip(), (text[start:end] or "").strip()))
    return out


def _is_theme(title):
    t = title.lower()
    return not any(k in t for k in _NON_THEME)


def critique(brief_text, max_chars=None, config=None):
    """Inspect a finished brief and RETURN a list of findings (never mutate input).

    Each finding is {"severity", "code", "message"}. Pure + deterministic so it is
    free to run and fully testable. max_chars is the theme-scaled character cap (so
    overrun is judged against the same budget the Writer used); config supplies
    tunables (config.get(key, default), defaults reproduce sensible behaviour)."""
    cfg = config or {}
    text = brief_text or ""
    findings = []

    def add(sev, code, msg):
        findings.append({"severity": sev, "code": code, "message": msg})

    if not text.strip():
        add(CRITICAL, "empty_brief", "Brief is empty.")
        return findings

    sections = _sections(text)
    themes = [(t, b) for (t, b) in sections if _is_theme(t)]

    # 1. structure — there must be theme sections
    if not themes:
        add(CRITICAL, "no_themes", "No theme sections (no '## ' headings).")

    # 2. citations — anti-hallucination: the brief must cite real sources
    if not _LINK.search(text):
        add(CRITICAL, "no_citations", "No source citations (no links) anywhere in the brief.")
    else:
        for title, body in themes:
            if not _LINK.search(body):
                add(IMPORTANT, "theme_no_citation", f'Theme has no source link: "{title}".')

    # 3. a heading with no body underneath it
    for title, body in sections:
        if not body:
            add(IMPORTANT, "empty_section", f'Section has a heading but no body: "{title}".')

    # 4. character overrun vs the theme-scaled cap
    if max_chars:
        ratio = float(cfg.get("critic_overrun_warn_ratio",
                              cfg.get("writer_char_overrun_warn_ratio", 1.0)))
        n = len(text)
        if n > max_chars * ratio:
            pct = round((n / max_chars - 1) * 100)
            add(IMPORTANT, "char_overrun", f"Brief is {n} chars vs cap {max_chars} (+{pct}%).")
        elif n > max_chars:
            pct = round((n / max_chars - 1) * 100)
            add(MINOR, "char_over_cap", f"Brief is {n} chars, just over cap {max_chars} (+{pct}%).")

    # 5. thin theme count
    min_themes = int(cfg.get("critic_min_themes", cfg.get("writer_min_themes", 3)))
    if themes and len(themes) < min_themes:
        add(MINOR, "few_themes", f"Only {len(themes)} theme(s); expected at least {min_themes}.")

    # 6. currency — a '$' amount in a theme that itself cites a yen-linked source (2026-09-08).
    for cm in find_currency_mismatches(text):
        add(CRITICAL, "currency_yen_dollar_mismatch",
            f'Theme "{cm["theme"]}" states a $ amount but its own citations link to a '
            f'yen source ({", ".join(cm["yen_urls"][:2])}) — likely a mis-converted yen '
            f"figure; keep non-USD amounts in their original currency.")

    # 7. theme totals must equal the sum of their own listed components (2026-09-08).
    total_tol = float(cfg.get("critic_currency_total_tolerance_pct", 0.05))
    for tm in find_theme_total_mismatches(text, tolerance_pct=total_tol):
        add(IMPORTANT, "theme_total_mismatch",
            f'Theme "{tm["theme"]}" states a total of ~${tm["stated_millions"]:g}M but its '
            f'listed components sum to ~${tm["component_sum_millions"]:g}M '
            f'({tm["diff_pct"]:g}% off).')

    return findings


def theme_count(text):
    """Number of '## ' theme sections (excludes Highlights / Investigations)."""
    return sum(1 for (t, _b) in _sections(text) if _is_theme(t))


def worst_severity(findings):
    """Highest severity present, or None when there are no findings."""
    if not findings:
        return None
    return max((f["severity"] for f in findings), key=lambda s: _ORDER[s])


def at_or_above(findings, min_severity):
    """True if any finding is at or above min_severity (e.g. only alert on Important+). Pure.
    An unknown min_severity falls back to the Important floor."""
    floor = _ORDER.get(min_severity, _ORDER[IMPORTANT])
    return any(_ORDER.get(f.get("severity"), 0) >= floor for f in (findings or []))


def format_report(findings):
    """Mobile-first Telegram report, grouped by severity. Empty -> a clean-pass line."""
    if not findings:
        return "✅ Critic: no issues found."
    lines = ["🔎 Critic report:"]
    for sev in (CRITICAL, IMPORTANT, MINOR):
        group = [f for f in findings if f["severity"] == sev]
        if group:
            lines.append(f"\n*{sev}* ({len(group)})")
            lines.extend(f"• {f['message']}" for f in group)
    return "\n".join(lines)
