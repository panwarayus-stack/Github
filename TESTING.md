# Testing report

Run locally on Node 22.22.3 and Python 3.11.2 with Gradio 5.23.3.

- `npm test`: 5 passing tests: international numbering plans including shared +1/+7, invalid input, duplicate inventory, atomic reservations, duplicate payment submissions, expiration/release, two concurrent Node processes racing to reserve one listing, and a price change after confirmation.
- `python -m unittest discover -s tests -p 'test_*.py' -v`: 2 passing tests: import preview/commit with invalid and duplicate lines; online backup, SQLite integrity and restore into a new database; approval, refund, audit and illegal transition with mocked Telegram notifications.
- Started the real FastAPI/Gradio server locally: `/healthz` returned 503/degraded with an unconfigured bot, `/config` returned 401 without login, incorrect login returned 400, correct login returned 200 and authenticated `/config` returned 200. No credentials used in this check were real.
- Not tested: real Telegram bot startup/channel membership, messages/callback navigation, payment screenshot forwarding, real admin notifications, actual Space deployment, durable database after a Space restart, bucket connectivity or its write semantics, UptimeRobot external monitoring, complete end-to-end acceptance tests, production load/security. These are blockers, not passed acceptance tests.
