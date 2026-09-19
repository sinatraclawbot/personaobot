"""Plain-language hold/status copy for non-technical operators."""

REASON_COPY = {
    "owner_takeover": "The account owner replied in Telegram, so automatic replies are paused.",
    "unsupported_media": "This chat has a photo, voice note, or other media PersonaAI cannot read yet. A person can continue from here.",
    "consent_withdrawn": "The client asked not to be contacted. Replies are on hold.",
    "sexual_services": "Held because the chat moved into sexual services, which this profile does not offer.",
    "connection_permission_lost": "Telegram no longer lets this bot reply for this account. Check the business connection in Telegram.",
    "connection_refresh_denied": "Telegram would not confirm this connection, so sending is paused until it is reconnected.",
    "delivery_uncertain": "The last reply may or may not have reached Telegram. Check the chat before sending anything else.",
    "telegram_send_rejected": "Telegram declined the last reply. Nothing further was sent automatically.",
    "human_mode": "This profile is human-managed, so PersonaAI is waiting for a person to reply.",
    "automation_hourly_limit": "Automatic replies paused after a busy hour. A person can continue, or resume in a little while.",
    "manual_gate_removed": "A manual approval step was removed, so this draft was set aside.",
    "client_returned": "The client wrote again after the owner replied, so automatic replies are back on.",
    "reply_window_expired": "Telegram's 24-hour reply window has closed. Wait for a new client message before sending.",
    "incoming_window_expired": "Telegram's 24-hour reply window has closed. Wait for a new client message before sending.",
    "operator_pause": "A teammate paused this conversation.",
    "operator_resume": "A teammate resumed this conversation.",
    "operator_block": "A teammate blocked this conversation.",
    "profile_not_enabled_or_reviewed": "This profile is paused or still waiting for a lawful-use review.",
    "conversation_not_active": "This conversation is not active, so automatic replies are off.",
    "minors": "Held for an age or safety concern. A person should review before anything is sent.",
    "coercion": "Held for a safety concern. A person should review before continuing.",
    "trafficking": "Held for a safety concern. A person should review before continuing.",
    "illegal_activity": "Held because the chat may involve something this profile cannot help with.",
    "uncertain": "PersonaAI was not sure this was safe to answer automatically, so a person should take a look.",
    "booking": "The client is asking about a booking or payment. A person should take it from here.",
    "privacy": "This involves private details. A person should continue.",
    "human_request": "The client asked to speak with a person.",
    "data_erased": "This conversation's content was erased.",
    "ai_unavailable": "The assistant is temporarily unavailable. Try again in a moment.",
    "ai_not_configured": "The assistant is not configured yet, so replies need a person.",
    "source_changed": "The conversation changed, so this draft was set aside.",
    "source_deleted": "A message was deleted, so this draft was set aside.",
    "profile_changed": "Profile settings changed, so this draft was set aside.",
    "context_changed": "The conversation moved on, so this draft is out of date.",
    "worker_interrupted_during_send": "Sending was interrupted. Check Telegram before writing again.",
    "approver_access_revoked": "The person who approved this draft no longer has access.",
    "empty_reply": "Type a message or attach a photo or video before sending.",
    "bad_file": "That file type is not supported. Use a photo (JPG/PNG/WebP) or video (MP4/MOV/M4V).",
}

DEFAULT_COPY = (
    "This conversation is waiting for a person to review. It is not broken — PersonaAI paused so nothing is sent by mistake."
)


def explain_reason(reason):
    if not reason:
        return ""
    return REASON_COPY.get(str(reason), DEFAULT_COPY)
