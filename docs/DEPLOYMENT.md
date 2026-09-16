# Deployment and operations runbook

## Minimum deployment

Use a Linux host or container platform with Python 3.12, PostgreSQL 16+, a valid HTTPS hostname, outbound HTTPS to Telegram/OpenAI and durable database storage. Start with one API and two to four workers for 10–20 profiles. Scale workers based on observed queue age, provider limits and traffic rather than profile count alone. The schema and locks support separate connections progressing concurrently; 100+ profiles still require load testing on the target host.

The supplied Compose file is a **development environment**. Its database uses a single administrative database role and an example password. Production should use a managed database, restricted application credentials, encrypted disks/backups, verified TLS (`sslmode=verify-full` with your provider's CA configuration) and infrastructure-level secret injection. Replace default passwords. Do not expose PostgreSQL publicly.

## Release sequence

1. Run CI against a disposable PostgreSQL database. Complete the live acceptance tests below. Review the exact application image/dependency scan.
2. Supply `ENVIRONMENT=production`, `APP_URL=https://your-hostname`, `COOKIE_SECURE=true`, `DATABASE_URL`, `TELEGRAM_BOT_TOKEN`, a random `TELEGRAM_WEBHOOK_SECRET` (32+ URL-safe characters), and `OPENAI_API_KEY`. Choose an accessible structured-output model via `OPENAI_MODEL` and validate it with your evaluation corpus. Secrets must not enter source control, image layers or shell history.
3. Take a database backup. Run `alembic upgrade head` once as a release job with migration privileges. Run `alembic check` to detect schema drift. Application startup never creates tables implicitly.
4. Deploy the API, workers and maintenance service from the same image. Use a non-root UID, read-only application filesystem, a temporary writable `/tmp`, and SIGTERM grace of at least 180 seconds. Normal worker leases last 600 seconds.
5. Put a TLS reverse proxy in front of the API. Preserve `Host`; set `APP_URL` to the exact public origin without a path. Do not allow arbitrary forwarded-client-IP headers. The default API ignores proxy headers; login source throttling then groups proxy traffic together, conservatively. To restore per-client IP limits, configure Uvicorn's trusted proxy IP list to only your proxy's addresses and enforce trusted headers there.
6. Create the first administrator using the interactive CLI. Add operators in Operations and assign only the needed profiles. Account creation is not public. Use a trusted secret-sharing channel for temporary credentials; rotate them using the CLI.
7. Register the webhook using `python -m app.cli webhook`. Inspect `python -m app.cli webhook-info`. Keep old pending updates; do not call `getUpdates` while a webhook is installed.
8. Start with one designated adult test account/profile in approval mode. Validate the full lifecycle below before onboarding other profiles or enabling automatic replies.

Example Caddy configuration for a host reverse proxy:

```caddyfile
your-hostname.example {
    request_body {
        max_size 256KB
    }
    reverse_proxy 127.0.0.1:8000
}
```

The application's own request cap is also enforced, including chunked bodies. Add edge request-rate and connection limits appropriate to your host. Give the Telegram webhook its own rate-limit policy so login throttling or UI traffic cannot starve delivery. Do not log webhook bodies, authorization headers, session cookies, bot tokens or client message content.

## Health and alerts

- `/health/live`: process liveness.
- `/health/ready`: database query and a worker heartbeat within 660 seconds. This detects a stopped worker; it does not prove that external credentials, all workers, or model access are healthy.
- Operations: queued/running/dead jobs, reason codes, unclaimed connections and recent audit events.
- Alert on readiness failures, growing queue age, dead jobs, unknown send outcomes, repeated permission failures, provider errors, maintenance failures and webhook pending-update growth. Container/service logging supplies sanitized job IDs/status/reason codes only.
- Maintenance runs hourly and processes up to 500 inactive conversations per pass. Investigate persistent `retention_failed` logs; scale the cleanup process or shorten the interval for large deletion backlogs.

No external alert destination is configured by the application. Wire these signals into your deployment's monitoring service. Do not depend on someone leaving the dashboard open to notice failures.

## Recovery

**Business Connection revoked / disabled / permissions changed:** pending drafts become stale or blocked; the conversation escalates. Have the account owner repair access in Telegram. After a fresh incoming message and operator review, resume the conversation. The pre-send refresh independently catches changes even if a webhook update was missed.

**Unclaimed connection:** verify the real account owner and create a profile with that exact numeric user ID. Do not match by display name or username. Retry dead inbound jobs from Operations. Owner bindings cannot be reassigned; create a separate profile if the owner changes.

**Expired reply window:** wait for a new incoming client message. Do not switch to ordinary bot messaging, a userbot, or another connection to circumvent the restriction.

**Unknown delivery:** `uncertain` means Telegram may have accepted the message. Check the actual Telegram conversation before composing a new message. The dashboard intentionally offers no retry button for send jobs. Mark the review in a conversation note and resume only after reconciliation. Never edit a draft back to queued directly in SQL.

**AI unavailable or questionable output:** leave the conversation escalated. Fix provider configuration, inspect redacted error codes, and resume after human review. Manual platform replies still need working safety classification; the platform does not silently bypass its safety engine during an outage.

**Worker restart:** leases expire and idempotent jobs are reclaimed. A persisted send intent becomes uncertain rather than being replayed. Do not reduce the worker lease below worst-case AI/Telegram request duration.

**Database unavailable:** webhooks return an error instead of acknowledging volatile data; Telegram may retry. Restore quickly and monitor webhook backlog because Telegram does not retain updates indefinitely.

## Backups and migrations

Use managed PostgreSQL point-in-time recovery where available. Test restores into an isolated database and verify profile/conversation counts, FK constraints and app startup. Example logical backup for a local Compose deployment:

```sh
docker compose exec -T db pg_dump -U platform -d platform -Fc > backup.dump
```

Backups contain sensitive conversation data: encrypt them, limit access and set retention. Restore procedures must account for already-sent drafts and old webhook job deduplication state. Pause sending while reconciling an older restore with Telegram to avoid replaying historical work. Prefer restoring and applying forward fixes to downgrading a production schema. The initial downgrade drops all tables and is for disposable test databases only.

## Live acceptance before production use

- Two Business accounts receiving messages from the same client produce separate conversations, AI contexts, notes, prices and drafts.
- Ordinary bot messages and bot-sent echoes never trigger Business replies.
- Unknown connection metadata is recovered; unknown owners remain unclaimed.
- Disable/revoke reply rights while a draft is waiting; approval must not cause delivery.
- Edit/delete a source message; prior drafts become stale, deleted text is removed and memory is invalidated.
- Reply as the account owner; automation pauses. Revoke an approver's access; their queued draft cannot send.
- Exercise a genuinely expired 24-hour window using a designated test chat, without changing Telegram clocks or bypassing its rules.
- Test underage/sexual-service/coercive/trafficking/illegal/ambiguous requests, human requests, unsupported media, opt-outs and prompt injection in every enabled language. Use synthetic test data and human review; do not send harmful test content to real clients.
- Simulate a worker interruption before/after a send intent and a Telegram 429; inspect the resulting `uncertain`/retry behavior without causing duplicate delivery.
- Confirm login, CSRF, membership boundaries, cookie security, profile activation, health alerts, retention and database restore.

The shipped CI, unit/HTTP tests and mocks cover these control paths, but real Telegram entitlements and provider classification accuracy must be verified with credentials and designated test accounts.

## Local testing without public hosting

Run `docker compose -f compose.yaml -f compose.local.yaml up --build -d` to include
an optional local receiver. It uses official Bot API long polling and forwards
Business updates into the same authenticated, durable webhook inbox. It confirms
updates to Telegram only after successful persistence; retries are deduplicated.
Docker must remain running and the Mac must stay awake. Run only one receiver per
bot. Configured reply mode and automatic safety checks still apply.

Before configuring a public webhook, stop local polling with
`docker compose -f compose.yaml -f compose.local.yaml stop receiver`.
The receiver refuses production mode and pauses if it detects an existing webhook;
it never deletes a webhook. Production should use the HTTPS webhook deployment above.
