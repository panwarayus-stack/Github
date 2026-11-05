---
title: Country Number Marketplace (development)
sdk: gradio
sdk_version: 5.23.3
python_version: 3.12.12
app_file: app.py
---

# Country Number Marketplace — development implementation

**Not production-ready. Do not accept real payments or customer data with this build.** This repository contains a functional local prototype, not the complete marketplace specified in the request. It has not been deployed or tested with a real Telegram bot, a Hugging Face Space, a bucket, or UptimeRobot. Startup deliberately requires `ALLOW_UNSAFE_DEVELOPMENT=1`.

## What is implemented

- Telegraf private-chat bot with channel membership gate, dynamic services and countries, five-item browsing, random selection, transactional reservations and expiry, photo/reference submission, account history, update and support menus.
- SQLite schema and Node/Python access to the same database; integer minor-unit prices, unique live reservations, unique numbers, payment references and Telegram file IDs; atomic state transitions.
- Gradio dashboard with password authentication, overview, validated TXT preview/import, search and basic inventory changes, order review/approve/reject/cancel/refund records, screenshot retrieval, user block/unblock, reports, broadcast, online SQLite backup with integrity check, and audit log.
- FastAPI `/healthz`, bot supervisor and graceful shutdown. No GPU jobs are requested. No account resale, login sessions, OTP handling, or authentication-code forwarding is implemented.

## Important limitations and remaining work

1. **Durable transactional storage is not implemented for a free Hugging Face Space.** The live SQLite DB must be on a durable filesystem with working SQLite locking, shared by the bot and dashboard. A Hugging Face bucket is object storage and its mount semantics have not been verified here for SQLite transactions or locks. Do not put the live DB on a bucket mount or ephemeral Space storage and assume safe persistence. Use an external transactional database such as PostgreSQL and migrate the SQL and both clients before production. The backup directory can be on a bucket mount, but snapshots are not continuous persistence: changes since the last snapshot can be lost.
2. This is not a complete admin system: per-admin Telegram identity for dashboard access, country correction, deletion/editing, pricing defaults and bulk pricing, settings management, service management, order-event history, scheduled backups, automatic restore, notification retry/outbox, and some requested statistics are missing. Dashboard uses one shared username/password, so audit identifies that account, not the individual administrator's Telegram ID.
3. No end-to-end Telegram acceptance tests, real Space restart, bucket integrity under interruption, or actual external health checks were performed. Payment review and Telegram notifications need an operational reconciliation workflow. A failed admin notification does not retry. Matching duplicate references/photos is only a heuristic and does not establish payment authenticity. Review against the payment provider before approval. A refund record does not send money.
4. `PAYMENT_SUBMITTED` and `UNDER_REVIEW` orders remain reserved until an administrator decides; only unpaid `PENDING_PAYMENT` orders expire. No order delivery/number activation or carrier integration is implemented. Admins must arrange legitimate service fulfillment outside this prototype.
5. `/healthz` tests SQLite connectivity, directory writability and whether a bot process is running; it does not prove Telegram connectivity, mount durability or successful synchronization to a bucket. Process supervision and a local lock do not prevent two different Space instances from polling the same bot. Use a single deployment; resilient leader election is still needed. No cross-restart broadcast resume/deduplication is provided.
6. No production security review, encryption/retention policy for personal data, role-based authorization, hardened rate limiting, durable notification queue, payment-provider integration or disaster-recovery exercise has been completed. Do not use this as a public financial service.

## Local installation and testing

Requires Python 3.11+ and Node 22.5+. Python dependencies include `nodejs-wheel==22.20.0` so the virtual environment supplies Node and npm when activated. On Linux:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
npm ci --ignore-scripts
cp .env.example .env
mkdir -p data/backups
# Edit .env; do not commit it.
python app.py
```

Open `http://localhost:7860`, log in with the configured dashboard username/password (minimum 16 characters). The bot needs real `BOT_TOKEN`, numeric `OWNER_ID`, `CHANNEL_ID`, `CHANNEL_URL`, and Telegram `PAYMENT_QR_FILE_ID`. Create the bot using BotFather, add it as an administrator of the mandatory channel so `getChatMember` can check other users, and start a private chat with the bot and with each administrator. `CHANNEL_ID` may be an `@channelusername` or numeric chat ID. `ADMIN_IDS` is a comma-separated list of numeric Telegram IDs. Obtain the QR file ID with a trusted Telegram client/API workflow; never put a secret into source control. The configured currency uses two decimal places regardless of currency. `OWNER_USERNAME` and `SUPPORT_USERNAME` omit `@`.

Run automated checks:

```bash
npm test
python -m unittest discover -s tests -p 'test_*.py' -v
```

See [TESTING.md](TESTING.md) for results and untested items.

## Hugging Face: experimental deployment only

The YAML header selects the Gradio SDK and Python 3.12.12. The pinned Python `nodejs-wheel` provides Node/npm; on first launch the app runs `npm ci --ignore-scripts` from the lockfile. It binds `0.0.0.0:7860`. In Space Settings, select ZeroGPU if eligible; this app has no GPU-decorated functions and therefore requests no GPU job. Free compute may sleep; UptimeRobot is not a guarantee of continuous execution. HF currently documents ZeroGPU as Gradio-SDK-only and free personal ZeroGPU eligibility can be limited. Check current account and billing eligibility before deployment.

For an **experiment with disposable data only**, create a Gradio Space with these files, set the values from `.env.example` as Space secrets/variables (particularly bot token, dashboard password and IDs; do not upload `.env`), and explicitly set `ALLOW_UNSAFE_DEVELOPMENT=1`. `DATABASE_PATH` on the default Space filesystem is ephemeral and **will be lost on restart**. Do not use real customer/payment records. This is intentionally not a complete production deployment guide because the required durable transactional database integration is missing.

For backup experiments, create a private bucket and attach it in Space Settings → Storage Buckets at a path **you choose**, for example `/marketplace-backups`. Set `BACKUP_DIR=/marketplace-backups`, then factory-rebuild the Space if required for the mount to appear. Bucket mounts are runtime-only; confirm availability and permissions before running a backup. Create the directory in local development instead. Dashboard → Storage and backups makes uniquely named SQLite snapshots, checks `PRAGMA integrity_check`, and stores the SHA-256 in the live database. Never rely on these snapshots as the only copy; secure bucket access and verify backups independently. No automatic backups are configured.

Restoring a snapshot for local testing: stop the bot and dashboard completely, copy the snapshot to a **new** path, run `sqlite3 new.db 'PRAGMA integrity_check;'`, verify its SHA-256 using the recorded hash, and point `DATABASE_PATH` to it before restarting. Do not overwrite the only valid backup. Verify recovery with a test copy and understand that records created after the snapshot are absent. The backup history table inside a snapshot will not include the snapshot's own later history entry.

For UptimeRobot configure an HTTPS monitor for `https://YOUR-SPACE-URL/healthz`, accepting HTTP 200 and alerting on 503 or timeouts. Never include secrets in the URL. With incomplete bot config it returns 503. The endpoint is public, provides only coarse process/storage state, and cannot independently verify bucket durability or prevent sleeping. After deploying, test it externally and configure alerts. For any real service, first implement durable external database access and reliable background/notification processing, then repeat security and end-to-end testing.

References: [HF Spaces storage](https://huggingface.co/docs/hub/en/spaces-storage), [bucket access](https://huggingface.co/docs/hub/storage-buckets-access), [ZeroGPU](https://huggingface.co/docs/hub/en/spaces-zerogpu), [Spaces lifecycle](https://huggingface.co/docs/hub/spaces-overview), [Spaces dependencies](https://huggingface.co/docs/hub/en/spaces-dependencies).
