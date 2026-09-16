# Render deployment and migration

`render.yaml` defines a paid Docker web service, a paid Docker worker, an hourly
cleanup cron job, and PostgreSQL 16 in Frankfurt. It uses 512 MB web/worker
instances and a 256 MB database with 5 GB storage as an initial small deployment;
measure resource usage before onboarding many profiles. Confirm the actual Render
checkout estimate before provisioning. No resources have been created by preparing
this file. AI usage is separate.

## Deploy

1. Put the project root in a private GitHub repository. Do not upload `.env`,
   database dumps or client content. Connect the repository in Render Blueprints.
2. Review names against existing resources to avoid adopting an unrelated service.
   Review Render's current cost estimate and choose the appropriate workspace.
3. Enter secrets through Render's environment settings. Use a newly rotated Telegram
   token (the earlier token appeared in local diagnostic output). Set a fresh
   Telegram webhook secret of at least 32 characters, and the OpenAI API key.
4. Set APP_URL to the web service's exact HTTPS address. If Render assigns a suffixed
   hostname, update APP_URL on the web service and sync/redeploy the linked worker
   and cleanup job. This origin controls host and CSRF checks.
5. `python -m app.cloud web` honors Render's PORT; all service entry points serialize
   Alembic upgrades with a PostgreSQL advisory lock. Environment validation requires
   HTTPS and secure cookies. Render-style database URLs use the installed psycopg driver.
6. Check `/health/ready`. Do not register Telegram's webhook until the data transfer
   and account verification below are complete. Do not run the local receiver on Render.

## Transfer the existing installation

Schedule a short cutover. Keep the local database volume as a rollback copy.
Stop local receiver, worker, maintenance and API so the final backup is consistent
with respect to messaging and account edits. Telegram temporarily queues new updates;
complete the cutover promptly because it does not retain them indefinitely.

Take a private PostgreSQL custom-format dump with no owner/ACL dependencies. Do not
put dumps in GitHub or source downloads. Suspend the cloud worker and cleanup job
and prevent API writes before restoring. Restore into the newly provisioned empty
application database, verify table counts and migration revision, and invalidate
old sessions. Preserve existing users/password hashes, profiles, memberships,
connections, message history, deduplication records, drafts and send uncertainty.
Do not retry historical uncertain deliveries.

The blueprint blocks external database connections. Use an authenticated Render
shell/private-network restore, or temporarily allow only the operator's IP with
TLS for migration and remove that rule immediately afterward. Never open the
database to all IPs just to migrate.

Resume cloud services, verify existing administrator login, and register the webhook
from the web service shell with `python -m app.cli webhook`. It preserves pending
updates. Verify `python -m app.cli webhook-info` and a harmless message from a
separate test account. Confirm one successful reply before considering cutover done.
Keep local services stopped to prevent double processing; do not delete their data.

## Rollback

If no cloud processing has occurred, remove the cloud webhook without dropping
updates and resume the local stack. If cloud processing has occurred, first reconcile
cloud messages, update IDs and send outcomes; blindly restarting the old database
can duplicate replies. Take a cloud backup before any rollback. Do not erase data
or recreate administrator credentials as a troubleshooting shortcut.

## Verification so far

The blueprint validates against Render's published JSON schema. Database URL
normalization tests and lint pass. Account sign-in, actual provisioning, data transfer,
cloud startup and end-to-end Telegram delivery are pending. This document describes
the intended procedure, not a claim that the app is already hosted.
