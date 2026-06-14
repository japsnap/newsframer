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
import re

CRITICAL, IMPORTANT, MINOR = "Critical", "Important", "Minor"
_ORDER = {CRITICAL: 3, IMPORTANT: 2, MINOR: 1}

# '## ' headings that are not themes, so the theme-count check stays fair.
_NON_THEME = ("highlights", "investigations")
_LINK = re.compile(r"\]\(https?://")        # a markdown [text](http...) citation
_H2 = re.compile(r"^##\s+(.*)$", re.MULTILINE)


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

    return findings


def worst_severity(findings):
    """Highest severity present, or None when there are no findings."""
    if not findings:
        return None
    return max((f["severity"] for f in findings), key=lambda s: _ORDER[s])


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
