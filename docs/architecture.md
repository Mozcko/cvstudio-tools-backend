# Architecture

## Stack

| Concern | Choice | Pinned version |
| :--- | :--- | :--- |
| Web framework | FastAPI on Uvicorn | 0.142.2 / 0.30.1 |
| Database | PostgreSQL 15 | — |
| ORM | SQLAlchemy 2 (async) with `asyncpg` | 2.0.31 / 0.29.0 |
| Migrations | Alembic (async env) | 1.13.1 |
| Settings | `pydantic-settings` | 2.3.4 |
| Auth | Clerk session JWTs, verified with `PyJWT[crypto]` | 2.15.1 |
| Clerk webhooks | `svix` | 1.24.0 |
| Payments | `stripe` | 10.1.0 |
| AI | `openai` SDK (`AsyncOpenAI`), with `httpx` pinned to match | 1.109.1 / 0.28.1 |
| Tests | `pytest`, `pytest-asyncio`, `pytest-cov`, `pytest-mock` | `requirements-dev.txt` |
| Lint / format / audit | `ruff`, `pip-audit` | `requirements-dev.txt` |
| Runtime | Python 3.11 (Docker image `python:3.11-slim`) | — |

## Directory map

```
src/
├── main.py                 App: logging, CORS, router mounting, /health
├── core/
│   ├── config.py           Settings (env vars), allowed origins
│   ├── security.py         Clerk token verification → user id
│   └── observability.py    Error reporting (Sentry) with personal data scrubbed
├── api/
│   ├── dependencies.py     get_db, get_current_user(_obj), require_pro, enforce_ai_quota
│   └── routers/
│       ├── cv.py           /cvs
│       ├── users.py        /users/me
│       ├── ai.py           /ai/rewrite · /ai/cover-letter · /ai/ats · /ai/improve (deprecated)
│       ├── billing.py      /billing/create-checkout-session
│       ├── promo.py        /promo/redeem
│       └── webhooks.py     /webhooks/stripe · /webhooks/clerk
├── db/database.py          Async engine, session factory, declarative Base
├── models/                 user · cv · promo (+ redemptions) · payment · ai_request
├── schemas/                cv · user · ai · billing · promo        (Pydantic)
├── services/
│   ├── pro.py              grant / revoke / expire Pro — the only place that changes it
│   ├── stripe_service.py   Webhook verification, payments, refunds
│   └── ai/                 base.py (client) · rewrite.py · ats.py · cover_letter.py
├── utils/sanitizer.py      mask_cv_pii / restore_cv_pii
└── scripts/upgrade_user.py CLI: grant Pro manually

migrations/                 Alembic env + revisions
scripts/start.sh            Production entrypoint: migrate, then serve on $PORT
test/                       pytest suite (needs PostgreSQL)
create_promo.py             CLI: create a promo code
Dockerfile, docker-compose.yml
requirements.txt            Runtime dependencies (production image)
requirements-dev.txt        + test, lint and audit tools
pyproject.toml              ruff, pytest and coverage configuration
Makefile                    Everyday tasks (`make help`)
.github/                    CI, deploy and security workflows; templates; Dependabot
CONTRIBUTING.md, SECURITY.md
GEMINI.md                   Context file for the Gemini CLI agent
```

Layering is **router → service → model** where there is logic worth sharing (Pro grants, Stripe,
AI). Plain CRUD routers query the database directly.

## Request lifecycle

1. **CORS** (`main.py`) — origins from `settings.allowed_origins`: `FRONTEND_URL` plus `localhost`,
   `127.0.0.1` and `[::1]` on port 4321.
2. **Routing** — every router is mounted under `/api/v1`. `/health` is the only route outside it.
3. **Authentication** — `get_current_user_id` verifies the Clerk token
   (see [auth-plans-billing.md](./auth-plans-billing.md)) and returns its `sub`.
4. **User bootstrap** — `get_current_user_obj` loads or creates the `users` row and applies Pro
   expiry. `get_current_user`, `require_pro` and `enforce_ai_quota` build on it.
5. **Handler** — runs with an `AsyncSession` from `get_db`. FastAPI resolves `get_db` once per
   request, so dependencies and the handler share one session. Sessions do not auto-commit; code
   calls `await db.commit()` where it writes.
6. **Response** — serialised through the route's `response_model`.

## Configuration (`src/core/config.py`)

`Settings` reads environment variables, falling back to a `.env` file in the working directory.
Unknown variables are ignored. `settings = Settings()` runs at import time, so a missing required
variable stops the process (and Alembic, and the tests) immediately.

| Variable | Required | Default | Used for |
| :--- | :---: | :--- | :--- |
| `DATABASE_URL` | ✅ | — | Postgres DSN. `postgres://` and `postgresql://` are rewritten to `postgresql+asyncpg://` |
| `CLERK_ISSUER` | ✅ | — | Clerk Frontend API URL (`https://…`). Token issuer and JWKS location |
| `CLERK_WEBHOOK_SECRET` | for the webhook | — | Verifying Clerk (Svix) webhooks |
| `CLERK_AUTHORIZED_PARTIES` | | the CORS origins | Comma-separated origins accepted in the token's `azp` |
| `ENVIRONMENT` | | `development` | `production` disables `/docs`, `/redoc`, `/openapi.json` |
| `DEBUG` | | `false` | `true` logs every SQL statement and sets log level to DEBUG |
| `FRONTEND_URL` | | `http://localhost:4321` | CORS origin, allowed token origin, Stripe return URLs |
| `OPENAI_API_KEY` | for AI | — | All AI features |
| `OPENAI_MODEL` | | `gpt-4o-mini` | Model for all AI features |
| `AI_RATE_LIMIT_PER_HOUR` / `_PER_DAY` | | `20` / `100` | Per-user AI call limits; `0` disables |
| `FREE_CV_LIMIT` | | `3` | CVs a non-Pro user may create |
| `FREE_IMPORT_LIMIT` | | `2` | AI-assisted CV imports a non-Pro user gets in total; `0` disables |
| `FREE_AI_WEEKLY_LIMIT` | | `3` | Enhance / Optimize runs a non-Pro user gets per rolling 7 days; `0` disables |
| `FREE_PUBLIC_LINK_LIMIT` | | `1` | Public links a non-Pro user may have online |
| `VIEW_HASH_SECRET` | | random per start | Key for the anonymous visitor identifier; set it to keep unique-visitor counts stable across restarts |
| `INTERVIEW_DAILY_LIMIT` / `_MONTHLY_LIMIT` | | `3` / `30` | Mock interviews a premium user may start per 24 hours / 30 days; `0` disables that window |
| `OPENAI_STT_MODEL` / `OPENAI_TTS_MODEL` / `OPENAI_TTS_VOICE` | | see `.env.example` | Voice models for the mock interview |
| `STRIPE_API_KEY` | for checkout | — | Creating Checkout sessions |
| `STRIPE_WEBHOOK_SECRET` | for the webhook | — | Verifying Stripe webhooks |
| `STRIPE_PRICE_7D`, `_30D`, `_LIFETIME` | for checkout | — | Stripe price ids per plan |
| `SENTRY_DSN` | | — | Error reporting. Unset = nothing is sent |
| `PROJECT_NAME` | | `CV Studio Tools API` | OpenAPI title, `/health` |

## Database schema

Defined in `src/models/`, created and changed **only** through Alembic migrations.

### `users`

| Column | Type | Notes |
| :--- | :--- | :--- |
| `id` | `String` PK | The Clerk user id (`user_…`) |
| `email` | `String`, unique, nullable | Synced from Clerk webhooks; informational |
| `is_pro` | `Boolean`, default `False` | |
| `pro_expires_at` | `DateTime(tz)`, nullable | `NULL` while Pro = lifetime |
| `premium_until` | `DateTime(tz)`, nullable | End of the premium level (Active Hunt); lifetime users are premium without it |
| `created_at` / `updated_at` | `DateTime(tz)` | `updated_at` is `NULL` until the first update |

### `public_links` and `link_views`

`public_links`: one row per published CV — `cv_id` (unique, cascade), `user_id` (cascade),
`slug` (unique), `is_active`, `show_email`, `show_phone`, `indexable`, `views_seen_at`.

`link_views`: one row per counted visit — `link_id` (cascade), `viewed_at`, `visitor`,
`referrer_host`.

**View statistics store nothing that identifies a visitor.** `visitor` is an HMAC of the IP
address, the user agent and the link, with a key derived from `VIEW_HASH_SECRET` and the date: it
is the same for one person on one link during one day (so reloads are not counted twice, and
"unique visitors" works) and cannot be turned back into an IP or followed across days or links.
`referrer_host` is only the host of the referring page. Crawlers, link previews and scripts are
not counted, and the same visitor within 30 minutes is one view.

### `interview_sessions`

One row per mock interview; also what the interview caps are counted from. Deleted with the user.

| Column | Type | Notes |
| :--- | :--- | :--- |
| `id` | `UUID` PK | |
| `user_id` | `String` FK → `users.id`, cascade | Indexed with `created_at` |
| `title`, `language`, `job_description` | | Title is the job title found in the posting |
| `status` | `String` | `active` or `completed` |
| `questions` | `JSONB` | `[{type, text}]`, fixed when the session starts |
| `turns` | `JSONB` | `[{role, kind, question, text, at}]` — text only, never audio |
| `report` | `JSONB`, nullable | Written by `finish` |
| `audio_count` | `Integer` | Speech generated for this session |
| `created_at` / `completed_at` | `DateTime(tz)` | |

### `cvs`

| Column | Type | Notes |
| :--- | :--- | :--- |
| `id` | `UUID` PK, default `uuid4` | Generated server-side |
| `user_id` | `String` FK → `users.id` `ON DELETE CASCADE`, indexed | |
| `title` | `String`, not null | |
| `content` | `JSONB`, not null | Opaque — the frontend's `CVData`, or `{ "mode": "markdown", "markdown": "…" }` |
| `language` | `String`, server default `'ES'` | `ES` / `EN` / `PT` by convention; not validated |
| `theme` | `String`, nullable | Theme id chosen in the frontend; opaque here |
| `created_at` / `updated_at` | `DateTime(tz)` | |

### `promo_codes` and `promo_redemptions`

| Table | Columns |
| :--- | :--- |
| `promo_codes` | `id` UUID PK · `code` unique · `max_uses` (0 = unlimited) · `used_count` · `granted_days` (≥ 9999 = lifetime) · `is_active` · `created_at` |
| `promo_redemptions` | `id` UUID PK · `promo_id` FK cascade · `user_id` FK cascade · `created_at` · `UNIQUE(promo_id, user_id)` |

### `payments`

One row per completed Stripe Checkout session.

| Column | Notes |
| :--- | :--- |
| `session_id` PK | Stripe Checkout Session id — the idempotency key for webhook deliveries |
| `user_id` | Clerk id, **no foreign key**: the row outlives the user |
| `plan` | `'7'`, `'30'` or `'lifetime'` |
| `payment_intent` | Used to match `charge.refunded` |
| `granted_days` | `NULL` for lifetime |
| `created_at`, `refunded_at` | |

### `ai_requests`

One row per accepted AI call: `id`, `user_id` (FK cascade), `endpoint`, `created_at`, with an index
on `(user_id, created_at)`. Read by the rate limiter. Rows are never pruned.

The CV document's shape is owned by the frontend; see `docs/data-model.md` in the `cvstudio-tools`
repo. The only keys the backend looks inside are `personal.*` (PII masking and the cover-letter
header).

## External services

| Service | Direction | Where |
| :--- | :--- | :--- |
| Clerk | JWKS fetch for token verification; inbound webhooks | `core/security.py`, `routers/webhooks.py` |
| Stripe | outbound Checkout session creation; inbound webhook | `routers/billing.py`, `services/stripe_service.py` |
| OpenAI | outbound chat completions | `services/ai/*` |

## Logging

Unhandled errors and `ERROR`-level log records are reported to Sentry when `SENTRY_DSN` is set
(`src/core/observability.py`). Request bodies, query strings, cookies, credentials and stack-frame
variables are never included: CV content and job descriptions must not leave the server.

`main.py` configures the standard `logging` module (INFO, or DEBUG when `DEBUG=true`), writing to
stdout. Modules use `logging.getLogger(__name__)`. User content — CV data, job descriptions — is
not logged; provider failures are logged with a traceback and answered with a generic message.
