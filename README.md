# Kindred — Telegram Business AI workspace

A working multi-profile messaging MVP for lawful, consensual, **non-sexual adult social companionship**. One official Telegram bot serves independently configured Business accounts. Includes a FastAPI/Jinja dashboard, PostgreSQL schema and Alembic migration, durable workers, AI moderation/replies, approvals, escalations, authentication, membership access, audit records and retention cleanup.

**Delivery status:** implemented, locally tested, and exercised on a live local Compose stack (DIANA GFE `mode=auto`, Business connection with `can_reply`, outbound sends observed). This is still not a claim of a completed production launch. See [verification](docs/VERIFICATION.md) for evidence, remaining gaps (token rotation, production deploy, full disclosure reliability), and test counts.

## Start with Docker

Requires Docker with Compose v2. Commands below run from this directory.

```sh
cp .env.example .env
# Edit .env with your bot token, a random webhook secret, and OpenAI API key.
docker compose up --build -d
docker compose exec api python -m app.cli create-admin admin@example.com
```

The admin command prompts for a password; it does not ship a default login. Open `http://localhost:8000`. The dashboard runs without external credentials in development; sending and AI processing fail closed until configured. The Compose database password is for local development only.

To explore the interface with fictional, paused profiles on an empty development database:

```sh
docker compose exec api python -m app.cli demo
```

## Connect Telegram

1. Create your central bot using BotFather and enable **Secretary Mode** (Telegram's current Business bot terminology).
2. Expose the API through HTTPS. Set `APP_URL` to that exact origin, `COOKIE_SECURE=true`, and `ENVIRONMENT=production`. Supply all secrets; production startup rejects missing credentials and non-PostgreSQL databases.
3. Generate a webhook secret with `python -m app.cli secret`; store it in the environment. Recreate the API, worker and maintenance containers after environment changes.
4. Register the webhook with `docker compose exec api python -m app.cli webhook`. It subscribes to all four Business update types and preserves pending updates.
5. Create a dashboard profile using the Business account owner's **numeric Telegram user ID**. That account owner connects the bot in Telegram and grants access only to intended private chats and reply permissions.
6. Connections match the exact owner ID. Unknown owners remain unclaimed in Operations. Add the correct profile, then retry dead inbound jobs from Operations if needed. Never bind by username or client chat ID.
7. Configure the profile's voice, languages, informational pricing, availability, boundaries and meeting rules. Review its lawful/adult scope before enabling it. Approval mode is the default.
8. Incoming messages in Auto mode generate replies without manual verification. Automatic policy checks still block prohibited content and hold uncertain requests. A client message is required within Telegram's reply window.
9. Review and approve the draft. The worker checks the content, refreshes the connection using `getBusinessConnection`, validates `is_enabled` and `rights.can_reply`, and sends with the exact `business_connection_id`.

The app does not perform identity verification. Automatic replies do not assert or certify a client's age or consent.

## Implemented behavior

- **Business routing:** `business_connection`, `business_message`, `edited_business_message`, `deleted_business_messages`; authenticated webhooks, persistent update deduplication, unknown-connection recovery, disabled/revoked-connection handling, owner-takeover detection and bot-loop suppression.
- **Isolation:** immutable owner bindings, connection/chat conversation identity, explicit profile scopes on reads, composite foreign keys for messages/drafts/memory, membership checks on every operator route, independent AI requests with no shared conversation IDs or retrieval tools.
- **Reply workflow:** automatic, approval and human modes; editable/rejectable drafts; queued manual replies with the same guards; revision checks; stale-draft cancellation on configuration/context changes; 24-hour eligibility with a conservative one-minute margin.
- **Safety:** deterministic high-risk/opt-out gates, OpenAI moderation, structured semantic policy decisions and independent outgoing review. Unsafe, ambiguous, booking/commitment and human-request decisions stop automated delivery. Unsupported media is escalated. Provider failure/refusal/incomplete output fails closed.
- **Durability:** PostgreSQL queue, leases, `FOR UPDATE SKIP LOCKED`, advisory connection locks across external-send intent commits, backoff, explicit 429 retry handling and dead-letter review. Unknown send outcomes are marked `uncertain`, never blindly resent.
- **Dashboard:** profile editor, filterable/paginated inbox, paginated transcript, draft approval, pause/resume/block, curated private memory, operator creation and profile access management, jobs and audit activity.
- **Security/operations:** Argon2 passwords, hashed server-side session tokens, origin + CSRF protection, login limits, secure production cookies, CSP, escaped HTML, request-size cap, health endpoints, content-redacted errors, non-root containers, recurring retention cleanup.

## Local development and tests

Python 3.12 is the supported runtime. PostgreSQL is required for production and concurrent workers. SQLite is only for local UI and isolated tests; it cannot test PostgreSQL locking semantics.

```sh
python3.12 -m venv .venv
. .venv/bin/activate
pip install --require-hashes -r requirements-dev.txt
export DATABASE_URL=sqlite:///./local.db
alembic upgrade head
python -m app.cli create-admin admin@example.com
uvicorn app.main:app --reload
# In another terminal with the same environment:
python -m app.worker
```

```sh
pytest -q
ruff check app tests
# WARNING: use a DISPOSABLE database. The test suite drops and recreates application tables.
TEST_POSTGRES_URL=postgresql+psycopg://user:password@localhost/platform_test pytest -q
```

GitHub Actions includes PostgreSQL tests, schema drift checks, a Docker build and a dependency vulnerability audit. The fully resolved dependency files include hashes; edit `requirements.in` / `requirements-dev.in` and regenerate locks with `uv pip compile --universal --python-version 3.12 --generate-hashes` when updating dependencies.

## Operations reference

```sh
python -m app.cli webhook-info
python -m app.cli set-password operator@example.com
python -m app.cli disable-user operator@example.com
python -m app.cli purge
python -m app.cli erase-conversation PROFILE_ID CONVERSATION_ID
```

Password changes and account disabling revoke existing sessions. Erasure removes stored content and memory, clears verification, cancels dependent work and retains minimal deduplication tombstones. Backup deletion follows the separate backup retention policy.

Read [architecture](docs/ARCHITECTURE.md), [Telegram contract](docs/TELEGRAM.md), [safety and privacy](docs/SAFETY.md), [deployment](docs/DEPLOYMENT.md), and [verification](docs/VERIFICATION.md) before operating with real clients.
