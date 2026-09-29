"""
Reply persona + content-scope policy (Phase 2 — the "ask the administrator" assistant).

Builds the system prompt for answering replies in a group/DM, plus a cheap pre-guard for the one thing
we must never get wrong: leaking anything about the operator. The assistant is the ADMINISTRATOR's
assistant — it never names a "boss".

Scope it MAY answer:  general / everyday questions; the NEWS it delivers (this chat's topics + today's
brief); and people who are part of THIS same chat.
Scope it MUST decline (politely, offering news/general help):  anything about the OPERATOR /
administrator personally; anything about OTHER subscribers or other chats/groups; anything outside
this chat's scope (system internals, configuration, who-is-subscribed-to-what). Settings/subscription
changes are never executed here — they route to the administrator for approval.

The policy text is a config-overridable template (reply_system_prompt_template); the default below
reproduces the intended policy. Topics / language / labels are injected at build time (no hardcoding).
"""

LANG_NAMES = {"en": "English", "ur": "Urdu", "ja": "Japanese", "ar": "Arabic", "hi": "Hindi"}

DEFAULT_TEMPLATE = (
    "You are {admin}'s assistant in this {surface} chat. You help the people in THIS chat only.\n"
    "\n"
    "YOU MAY answer:\n"
    "- general / everyday questions;\n"
    "- questions about the news you deliver here — today's briefing and these topics: {topics};\n"
    "- questions about people who are part of THIS same chat.\n"
    "\n"
    "YOU MUST NOT answer (politely decline, then offer news or a general question instead):\n"
    "- anything about {admin} or the operator personally — who they are, their details, or their other work;\n"
    "- anything about OTHER people who are signed up, or any OTHER chat/group or its content;\n"
    "- anything outside this chat — system internals, configuration, or who is subscribed to what.\n"
    "If asked to CHANGE settings, topics, or a subscription, do NOT do it yourself — say you'll check "
    "with {admin} and get back to them.\n"
    "\n"
    "Answer in {language}. Keep it short (a few sentences). If you don't know or it's out of scope, say "
    "so briefly. End with a short offer to help with the news or a general question."
)


def build_system_prompt(settings, available_topics, surface="group", language="en"):
    """Assemble the assistant's system prompt for one chat. `settings` = effective per-chat config.
    `available_topics` = the topics this chat is subscribed to (injected, not hardcoded)."""
    tmpl = settings.get("reply_system_prompt_template") or DEFAULT_TEMPLATE
    admin = settings.get("administrator_label", "the administrator")
    topics = ", ".join(available_topics) if available_topics else "the subscribed topics"
    lang_name = (settings.get("language_labels") or LANG_NAMES).get(language, language)
    return (tmpl
            .replace("{admin}", admin)
            .replace("{surface}", surface)
            .replace("{topics}", topics)
            .replace("{language}", lang_name))


def mentions_operator(text, operator_aliases):
    """Cheap pre-guard: True if the message is obviously asking about the operator/administrator. The
    main enforcement is the system prompt; this is a belt-and-suspenders hard-decline path the caller
    can use to refuse without even spending an LLM call."""
    t = (text or "").lower()
    return any(a and a.lower() in t for a in (operator_aliases or []))
