"""
Signup elicitation (Phase 2 — concierge / NF-E1).

When a NEW person asks to subscribe, the assistant sends ONE message asking for exactly what's needed
to deliver them news — and nothing more: phone (with country code), which of the OFFERED topics, news
length, and (optionally) a NEW topic they'd like. The reply is parsed into a structured record that
pre-fills the future dashboard's signup fields, so onboarding is one round-trip, not an interrogation.

Pure logic: builds the message + extracts what it can from a free-text reply (phone / topics / length).
A new-topic request is captured verbatim so the dashboard can fill the rest later. (The LLM can refine
the parse, but these deterministic matchers cover the common case and are testable.)
"""
import re

# The fields a completed signup fills, for the future dashboard auto-fill.
SIGNUP_FIELDS = ["phone_e164", "topics", "length", "new_topic_request", "language", "notes"]

_PHONE_RE = re.compile(r"\+\d[\d\s().\-]{6,}\d")


def blank_signup():
    return {k: ([] if k == "topics" else None) for k in SIGNUP_FIELDS}


def build_signup_message(available_topics, length_options=None, administrator_label="the administrator"):
    """The single elicitation message. Lists the offered topics so the person can just pick. Asks only
    what's necessary to deliver the news; the new-topic ask is optional."""
    length_options = length_options or ["short", "medium", "long"]
    topics_line = ", ".join(available_topics) if available_topics else "(ask me for the current list)"
    lengths = " / ".join(length_options)
    return (
        "Welcome! I can set you up to receive the news brief. To get started, reply in ONE message with:\n"
        "1) Your phone number with country code — e.g. +81 90 1234 5678.\n"
        f"2) The topics you'd like — pick any from: {topics_line}.\n"
        f"3) How long each brief should be: {lengths}.\n"
        "4) (Optional) A topic you don't see above but want — just name it and I'll pass it on.\n"
        f"Once you reply, I'll set it up with {administrator_label}'s approval and confirm back to you."
    )


def extract_phone(text):
    """First +country-code phone number in the text, normalized to +digits. None if absent/too short."""
    m = _PHONE_RE.search(text or "")
    if not m:
        return None
    digits = re.sub(r"[^\d+]", "", m.group(0))
    return digits if len(re.sub(r"\D", "", digits)) >= 8 else None


def match_topics(text, available_topics):
    """Which of the OFFERED topics the reply names (case-insensitive substring). Only offered topics —
    an off-list ask is captured separately as a new-topic request."""
    t = (text or "").lower()
    return [topic for topic in (available_topics or []) if topic and topic.lower() in t]


def match_length(text, length_options=None):
    """Which news length the reply asks for, or None."""
    t = (text or "").lower()
    for opt in (length_options or ["short", "medium", "long"]):
        if opt and opt.lower() in t:
            return opt
    return None


def parse_signup(text, available_topics, length_options=None):
    """Best-effort structured record from a free-text signup reply (deterministic part). The dashboard
    can show this pre-filled; the LLM/administrator confirms or completes it. Topics found off-list are
    NOT invented — any new-topic ask is left to `new_topic_request` (filled by the LLM/operator)."""
    rec = blank_signup()
    rec["phone_e164"] = extract_phone(text)
    rec["topics"] = match_topics(text, available_topics)
    rec["length"] = match_length(text, length_options)
    return rec
