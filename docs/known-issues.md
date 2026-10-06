# Known Issues and Gotchas

What is still open after the `fix/known-issues` round. Confidence labels:

- **Read** — follows directly from the code.
- **Ran** — verified by executing it (the test suite and the migrations were run against
  PostgreSQL in containers).
- **Not exercised** — implemented and unit/integration tested with fakes, but not run against the
  real external service.

Delete entries as they are resolved.

## Needs a manual pass before production

### 1. Real Clerk, Stripe and OpenAI were not exercised — Not exercised
Token verification is tested with a locally generated key, Clerk webhooks with real Svix signing
but a test secret, Stripe webhooks with the signature check stubbed, and AI with a fake client.
Before relying on this in production:

- sign in through the real frontend and confirm `/users/me` answers `200` (this proves
  `CLERK_ISSUER` and the `azp` origin are right — a wrong value shows up as `401` on every request);
- send a test event from the Clerk dashboard and from `stripe trigger checkout.session.completed`;
- run each AI feature once with a real key.

### 2. Deploying needs new configuration first — Read
`CLERK_ISSUER` is required and `CLERK_WEBHOOK_SECRET` is needed for the Clerk webhook. Without the
first the service does not start; without the second the webhook answers `500`. See the checklist
in the frontend repo's `PROD-ENV-CHECKLIST.md`.

### 3. Existing Stripe webhook registration may need updating — Read
The endpoint is `/api/v1/webhooks/stripe`, and it now also consumes
`checkout.session.async_payment_succeeded` and `charge.refunded`. Add those events to the
registered endpoint or refunds will not revoke access.

## Open limitations

### 4. Partial refunds and disputes do nothing — Read
Only a full refund (`charge.refunded` with `refunded: true`) revokes a grant. Partial refunds,
disputes and chargebacks are ignored.

### 5. Payments made before this version have no `payments` row — Read
Refunding one of those will not revoke access automatically; adjust the user by hand.

### 6. Promo redemptions before this version are not recorded — Read
The one-per-user rule starts counting now: someone who redeemed a multi-use code earlier can redeem
it once more.

### 7. `ai_requests` grows without bound — Read
One row per AI call and nothing prunes it. The rate limiter only reads the last 24 hours; a
periodic `DELETE … WHERE created_at < now() - interval '90 days'` would be enough.

### 8. Rate limiting counts attempts, not successes — Read
A call is recorded before the provider is contacted, so provider failures use up quota. This is
intentional (it bounds cost under failure) but can surprise a user during an outage.

### 9. AI output is not schema-validated — Read
`/ai/ats` returns whatever JSON object the model produced, and `/ai/rewrite` only guarantees an
object with the contact fields restored. The frontend merges defensively; another client would
need its own checks.

### 10. Authentication depends on reaching Clerk — Read
Verification needs Clerk's key set. Keys are cached, but a cold process that cannot reach Clerk
answers `503` to every authenticated request until it can.

### 11. No pagination on `GET /cvs/` — Read
Fine for the free tier (3 CVs); a Pro user with hundreds gets them all, content included, in one
response.

### 12. Expiry is lazy — Read
A user who never comes back keeps `is_pro = true` in the table after their pass ends. Any report
that counts Pro users must also check `pro_expires_at`.

### 13. Tests need PostgreSQL and wipe it — Read
There is no SQLite fallback (the models use `JSONB`/`UUID`). Locally, database-backed tests are
*skipped* when no database is reachable (CI fails on skips), and they drop every table in the
database they are pointed at. `make test` uses a dedicated `cvstudio_test` database.

### 14. The deploy workflow has not run against Railway — Not exercised
`deploy.yml` skips itself until the `RAILWAY_TOKEN` secret and `RAILWAY_SERVICE` variable exist,
so its `railway up` step has never executed. Watch the first real run, and disable Railway's own
GitHub auto-deploy at the same time or commits deploy twice.

### 15. No connection-pool or timeout tuning — Read
The SQLAlchemy engine and the OpenAI client use library defaults; a slow provider call holds a
request (and its database session) for as long as the SDK allows.

## Stale or to remove later

| Item | Status |
| :--- | :--- |
| `POST /ai/improve` | Deprecated shim for clients that predate `/ai/rewrite`; delete once the new frontend is deployed everywhere |
| `README.md` licence section | Placeholder text; setup section predates `CLERK_ISSUER` — use [development.md](./development.md) |
| `GEMINI.md` | Describes the old startup behaviour (tables created automatically) |
| Guards in the first two migrations | Needed only while pre-Alembic databases exist |

## Fixed in the `fix/known-issues` round

For reference when reading old notes or commits.

| Area | Now |
| :--- | :--- |
| Authentication and webhooks | Clerk tokens and Clerk/Stripe webhooks are cryptographically verified; required settings fail closed |
| AI privacy | Contact details are masked for every AI feature and restored in rewritten CVs |
| AI prompts | Action and language are validated fields; job descriptions travel as tagged data in the user message |
| AI errors | Non-Pro is `403`, rate limit `429`, provider trouble a generic `502`; internals are logged, not returned |
| AI cost | Per-user hourly and daily limits; request size caps |
| `/users/me` | Applies Pro expiry; returns only `id`, `is_pro`, `pro_expires_at` |
| Purchases | Extend remaining time instead of overwriting it; applied once per Checkout session; full refunds revoke |
| Promo codes | One redemption per user; single endpoint (`/billing/redeem` removed) |
| CVs | `theme` stored per CV; list is newest first; deleting a user cascades |
| Schema | Alembic migrations are complete and run at startup; no `create_all` |
| Operations | Production entrypoint without `--reload`, honours `$PORT`; SQL echo off by default; structured logging |
| Scripts | `upgrade_user.py` supports `--days` and uses the shared grant logic |
| Cleanup | DeepSeek wiring, unused modules, debug scripts and unused dependencies removed |
| Dependencies | FastAPI/Starlette, PyJWT and the OpenAI SDK upgraded to versions without known vulnerabilities; audited in CI |
| Pipeline | CI (lint, tests with 95% coverage floor, migrations, Docker smoke test, audit), CodeQL, Dependabot, gated deploy workflow |
