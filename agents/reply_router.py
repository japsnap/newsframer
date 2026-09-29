"""
Reply router (Phase 2 — NF-NEW5 + the reply-system backlog) — PURE decision logic.

When someone replies to a delivered message on any chat/surface, this decides — BEFORE any LLM call
or send — what to do, per that chat's config:
  - is the sender the OWNER (you)?  -> exempt from the rate limit, allowed to make changes.
  - is it a WRITE / settings / subscription request from a non-owner? -> route to the owner for
    approval ("ask my Boss"), never executed directly.
  - is the chat over its daily Q&A cap? -> politely decline until tomorrow.
  - otherwise -> answer, in the detected language (English reply -> English; Roman-Urdu -> Urdu).

It does NOT call an LLM, send anything, or mutate state — it returns a decision the caller acts on.
Everything is config-driven per chat (nothing hardcoded), so each group/DM can behave differently.
This is the shared, reusable core the WhatsApp concierge (NF-E1) and two-way replies (NF-NEW5) build on.
"""

# Decision actions
ANSWER = "answer"                                   # generate + send a normal Q&A answer
DENY_RATE_LIMITED = "deny_rate_limited"             # over the per-chat daily cap -> short 'try tomorrow' note
DENY_CONVERSATION_LIMIT = "deny_conversation_limit"  # too many back-and-forth turns in one conversation -> wrap up
OWNER_APPROVAL_REQUIRED = "owner_approval_required"  # write/settings request from a non-owner -> route to the administrator
IGNORED = "ignored"                                 # chat is read-only (permissions: read) -> no reply


def truncate_input(text, max_chars):
    """Cap an incoming reply before the model sees it, so one message can't blow up the token bill."""
    text = text or ""
    max_chars = int(max_chars or 0)
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + " …"


def chat_settings(chat_id, cfg):
    """Effective settings for a chat: defaults overlaid with this chat's overrides. Pure."""
    base = dict((cfg or {}).get("defaults", {}) or {})
    base.update(((cfg or {}).get("chats", {}) or {}).get(chat_id, {}) or {})
    return base


def is_owner(sender_id, owner_ids):
    return str(sender_id) in {str(o) for o in (owner_ids or [])}


def is_write_request(text, write_keywords):
    """True if the message asks to change settings/data/subscription (owner-only). Substring match on
    the configured keyword list (lowercased)."""
    t = (text or "").lower()
    return any(kw and kw.lower() in t for kw in (write_keywords or []))


def detect_reply_language(text, roman_urdu_markers, default_language="en"):
    """Roman-Urdu reply -> 'ur'; otherwise the chat's default. Heuristic via configured marker words
    (e.g. 'chahiye', 'batao') — settings-driven, never hardcoded."""
    t = (text or "").lower()
    if any(m and m.lower() in t for m in (roman_urdu_markers or [])):
        return "ur"
    return default_language


def decide(text, sender_id, settings, usage_today, owner_ids, turns_so_far=0):
    """Return {action, language, note}. `settings` is the effective per-chat config (chat_settings()).
    `usage_today` = member Q&A replies already handled for this chat today (briefings excluded by the
    caller). `turns_so_far` = back-and-forth turns already in THIS conversation. Pure + deterministic."""
    owner = is_owner(sender_id, owner_ids)
    lang = detect_reply_language(text, settings.get("roman_urdu_markers", []),
                                 settings.get("default_language", "en"))

    # A read-only chat never gets a reply (unless the owner is speaking).
    if str(settings.get("permissions", "qa")).lower() == "read" and not owner:
        return {"action": IGNORED, "language": lang, "note": "chat is read-only"}

    # Write / settings / subscription changes are owner-only; a non-owner is routed to the administrator.
    if is_write_request(text, settings.get("write_keywords", [])) and not owner:
        return {"action": OWNER_APPROVAL_REQUIRED, "language": lang,
                "note": "write/settings request from a non-owner -> route to the administrator"}

    # Per-conversation back-and-forth cap (owner exempt). 0 = unlimited.
    max_turns = int(settings.get("max_turns_per_conversation", 0) or 0)
    if not owner and max_turns > 0 and int(turns_so_far) >= max_turns:
        return {"action": DENY_CONVERSATION_LIMIT, "language": lang,
                "note": f"conversation over turn cap ({turns_so_far}/{max_turns})"}

    # Per-chat daily Q&A cap (owner exempt). 0 = unlimited.
    cap = int(settings.get("rate_limit_per_day", 20) or 0)
    if not owner and cap > 0 and int(usage_today) >= cap:
        return {"action": DENY_RATE_LIMITED, "language": lang,
                "note": f"over daily cap ({usage_today}/{cap})"}

    return {"action": ANSWER, "language": lang,
            "note": "owner" if owner else f"{int(usage_today) + 1}/{cap if cap else '∞'}"}
