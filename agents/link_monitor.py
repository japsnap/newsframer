"""
Bare-URL monitor (NF-NEW1 — "hyperlink the source name, never show a raw URL").

Pure logic, no I/O. NF-NEW1 requires every article citation in the Telegram brief to read
as a clickable SOURCE NAME (Markdown `[Source Name](url)`) with the URL hidden behind it —
never a bare/raw `https://...`. The format_rules prompt instructs the Writer to do this; this
module is the deterministic SAFETY NET that CATCHES a regression: it scans the produced brief
for any URL that is NOT the target of a Markdown link and flags it in the run log.

Like the NF-F2 char-overrun flag, this is a QUALITY signal, not a run-health failure — callers
print the flag and DO NOT change the agent_runs status, and it NEVER alters or blocks the brief.
A bare URL can't be safely auto-rewritten (we'd have to guess which source it belongs to), so we
surface it loudly instead of silently mangling the output.

    venv\\Scripts\\python.exe tests\\test_link_monitor.py
"""
import re

# Distinct, greppable marker so a log scan / monitor can match on it.
BARE_URL_MARKER = "⚠ BARE URL"

_URL_RE = re.compile(r"https?://", re.IGNORECASE)


def find_bare_urls(text):
    """Return a list of the bare URLs in `text` (a URL NOT already behind a Markdown link).

    A Markdown link writes the URL as `](url)` — so a URL is 'bare' when the two characters
    immediately before its scheme are NOT '](' . Pure; tolerant of non-string input (returns
    []). Returns the matched URL token up to the first whitespace, ')' or '<' so the log line
    is readable; this is for human eyes, not strict URL parsing."""
    try:
        text = str(text)
    except Exception:
        return []
    bare = []
    for m in _URL_RE.finditer(text):
        i = m.start()
        if text[max(0, i - 2):i] == "](":
            continue  # this URL is the target of a Markdown link — fine
        # grab the visible URL token for the log message
        tail = text[i:]
        token = re.split(r"[\s)<>\]]", tail, maxsplit=1)[0]
        bare.append(token)
    return bare


def bare_url_flag(text):
    """Return a one-line flag string when the brief contains bare URLs, else None.

    Log-only (NF-NEW1 / mirrors the NF-F2 char flag): never alters or blocks the brief.
    Lists up to 3 offending URLs so a human can spot which citation slipped."""
    bare = find_bare_urls(text)
    if not bare:
        return None
    shown = ", ".join(bare[:3])
    more = f" (+{len(bare) - 3} more)" if len(bare) > 3 else ""
    return f"{BARE_URL_MARKER}: {len(bare)} raw URL(s) not behind a source-name link: {shown}{more}"
