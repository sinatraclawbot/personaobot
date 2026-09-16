# Verified Telegram contract

Reviewed against official documentation on **2026-09-16**. Runtime uses only `https://api.telegram.org/bot<TOKEN>/<METHOD>`; there is no MTProto, userbot login, account session or unofficial API.

| Official behavior | Implementation |
|---|---|
| Secretary Mode allows the account owner to connect a bot and choose accessible chats | Enable through BotFather and the owner's Telegram settings; configure an exact numeric owner ID |
| Business Connection updates signal establishment, edits and termination | Persist enabled state, rights and owner; invalidate drafts on permission loss |
| Business messages carry a `business_connection_id`; their chat namespace is independent of ordinary bot chats with the same ID | Unique connection/chat pair, explicit profile scope and composite foreign keys; ordinary bot updates ignored |
| `BusinessConnection.rights.can_reply` permits replies/edits in private chats with incoming messages in the last 24 hours | Inspect nested rights; refresh via `getBusinessConnection` immediately before a send; use original incoming timestamp and a 60-second safety margin |
| `is_enabled` describes whether the connection is active | Both local eligibility and fresh remote state must permit sending |
| `getBusinessConnection` resolves a connection's current information | Recover unknown connection IDs and revalidate sends; unknown owners never receive auto-created profiles |
| Four Business update types include edits and deletions | All are registered and processed; deleted IDs leave tombstones, edits invalidate drafts |
| `sendMessage` accepts `business_connection_id` and a 1–4096-character text | Always include the connection ID; app caps reply text at 3,500; no parse mode or markup injection |
| `setWebhook.secret_token` is sent in `X-Telegram-Bot-Api-Secret-Token` | Constant-time comparison; require a strong token; acknowledge only after durable insert |
| Failed webhook deliveries may be retried; pending updates are not indefinite storage | Persist idempotency keys; monitor backlog and webhook status; do not drop pending updates on registration |
| Update IDs normally increase but may be randomized after at least a week without updates | Persistent deduplication plus timestamp-aware ordering; connection sequence comparison ages out |

Sources:

- [Business bots / Secretary Mode](https://core.telegram.org/bots/features#business-bots)
- [BusinessConnection](https://core.telegram.org/bots/api#businessconnection)
- [BusinessBotRights](https://core.telegram.org/bots/api#businessbotrights)
- [Message and its business_connection_id](https://core.telegram.org/bots/api#message)
- [BusinessMessagesDeleted](https://core.telegram.org/bots/api#businessmessagesdeleted)
- [getBusinessConnection](https://core.telegram.org/bots/api#getbusinessconnection)
- [sendMessage](https://core.telegram.org/bots/api#sendmessage)
- [setWebhook](https://core.telegram.org/bots/api#setwebhook)
- [Update](https://core.telegram.org/bots/api#update)
- [Bot Developer Terms](https://telegram.org/tos/bot-developers)

Only reply rights are needed. Do not request account-editing, gift, balance, deletion or story permissions for this MVP. Account entitlement, Telegram UI labels and account-specific availability should be checked during real onboarding. The account owner still controls chat access; an enabled connection does not guarantee permission in every chat. Telegram's send result is authoritative.

The truncated requirement “The system must gracefully handle a Business Connection…” is interpreted as handling missing/unclaimed information, out-of-order state, edits, revocation, disablement, reconnection, changed connection IDs, insufficient rights, expired reply windows, transient API errors and unknown send outcomes. These choices are explicit rather than inferred hidden requirements.
