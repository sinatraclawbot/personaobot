# Verification record

Date: 2026-09-16. Runtime: Python 3.12.14. Environment: macOS desktop workspace.

## Completed

- Automated tests for Business update routing, exact profile/connection isolation, composite FK rejection, edit/delete ordering, tombstones, unknown/unclaimed connection handling, owner takeover, bot echoes, unsupported media, reply modes, safety decisions and provider failure.
- Send tests for revision changes, permission revocation, expiry during AI work, concurrent incoming work, manual-content checks, explicit 429 backoff, uncertain outcomes and interrupted send intents.
- Authentication/authorization tests for login/logout, session expiry, CSRF/origin checks, rate limits, stored HTML escaping, memberships and cross-profile access rejection.
- Full webhook → durable worker → AI generation → outgoing checks → Telegram send simulation using controlled external API responses.
- Alembic upgrade, schema drift check, downgrade and re-upgrade on an isolated SQLite database.
- Dependency vulnerability audit: **no known vulnerabilities** in the final hashed production lock at audit time. This is a point-in-time result, not a permanent security guarantee.
- Ruff lint.
- Browser verification using the Codex in-app browser: login, dashboard, transcript/drafts/verification UI, profile creation, saved profile edit after reload, operations page, and no JavaScript console errors on those flows. Desktop 1440×1080 and mobile 390×844; inbox and conversation document widths matched the mobile viewport.
- Browser testing discovered and fixed a real login issue: `Referrer-Policy: no-referrer` made form requests carry a null origin. The final policy is `same-origin`, preserving strict origin checks and cross-origin referrer privacy.

**Final automated result: 77 passed against PostgreSQL 16, no skipped tests.** This includes both concurrency tests for independent queue claims and connection locks across send-intent commits. The two warnings are upstream test-client deprecations. See `test-results.txt` for captured output.

PostgreSQL migrations and schema drift checks passed on a fresh, isolated Docker database. The Docker image built successfully with hashed dependencies. A separate Compose smoke test started the database, migration job, API, worker and maintenance service: readiness and login returned HTTP 200, the worker heartbeat was detected, and maintenance completed a cleanup pass. Temporary test containers were then removed. Existing user databases were not touched. See `docker-verification.txt` for a concise record.

## Live local stack (same day, operator Mac)

Evidence gathered against the running Compose stack (`personaai-*` services). No secrets recorded here.

- `/health/live` → `{"status":"ok"}`; `/health/ready` → `{"status":"ready"}`.
- Compose services up: api (healthy), db (healthy), worker, receiver, maintenance.
- Profile **DIANA GFE**: `mode=auto`, `enabled=true`, `lawful_reviewed=true`; boundaries filled with lawful non-sexual text; pricing left empty (operator skipped service list — general chat only).
- Business connection: `enabled=true`, `rights.can_reply=true`.
- Recent worker jobs (`update` / `generate` / `send`) completing with `status=done`.
- Live Telegram `getMe`: `can_connect_to_business=true` (username/id present; values not logged).
- Operator-visible draft previews show AI disclosure language on English replies (e.g. “I'm the AI assistant…”). Hebrew drafts also sent; full disclosure reliability across every language/turn is **not** claimed as fully proven.
- `app/explanations.py` + templates present; unit tests cover explanation strings; httpx noise silenced; api+worker images rebuilt.
- Automated SQLite suite (this pass): **83 passed, 2 skipped** (postgres-only locks). Offline `local_risk` vs `safety-cases.jsonl`: 12/14 pass as prefilter; 2 multilingual-minors cases rely on semantic AI (expected for the deterministic gate).

## Not verified in this environment


- **Token rotation:** skipped by operator; bot token not rotated during this session.
- **Production deploy / public HTTPS webhook / COOKIE_SECURE production hardening:** not performed. Current stack is local Compose + local receiver path.
- **Full AI disclosure reliability:** English drafts observed with disclosure; not exhaustively verified for every language, every turn, or every edit path.
- **Measured live-model classification accuracy:** not measured. Unit tests use FakeAI / MockTransport; offline local_risk is a prefilter only. Multilingual age cues still depend on semantic policy.
- **Load testing / 100+ profile capacity / production restore / penetration testing:** not performed.

The result is an implemented system with a working local live path (auto mode replies observed). It is not represented as a production-certified or publicly deployed service.
