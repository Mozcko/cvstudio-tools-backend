# Architecture

## Stack

| Concern | Choice | Version pinned in `requirements.txt` |
| :--- | :--- | :--- |
| Web framework | FastAPI on Uvicorn | 0.111.0 / 0.30.1 |
| Database | PostgreSQL 15 | — |
| ORM | SQLAlchemy 2 (async) with `asyncpg` | 2.0.31 / 0.29.0 |
| Migrations | Alembic (async env) | 1.13.1 |
| Settings | `pydantic-settings` | 2.3.4 |
| Auth | Clerk session JWTs, decoded with `PyJWT` | 2.8.0 |
| Payments | `stripe` | 10.1.0 |
| AI | `openai` SDK (`AsyncOpenAI`) | 1.35.10 |
| Tests | `pytest`, `pytest-asyncio`, `httpx`, `pytest-mock` | — |
| Runtime | Python 3.11 (Docker image `python:3.11-slim`) | — |

`psycopg2-binary` and `python-multipart` are installed but not used by any code in `src/`.

## Directory map

```
src/
├── main.py                 App factory: lifespan (create tables), CORS, router mounting, /health
├── core/
│   ├── config.py           Settings (env vars), DATABASE_URL normalisation
│   └── security.py         get_current_user_id — Bearer token → Clerk user id
├── api/
│   ├── dependencies.py     get_db, get_current_user (ensures user row, expires Pro)
│   └── routers/
│       ├── cv.py           /cvs
│       ├── users.py        /users/me
│       ├── ai.py           /ai/improve · /ai/cover-letter · /ai/ats
│       ├── billing.py      /billing/create-checkout-session · /billing/redeem
│       ├── promo.py        /promo/redeem
│       └── webhooks.py     /webhooks/stripe · /webhooks/clerk
├── db/database.py          Async engine, session factory, declarative Base
├── models/                 user.py · cv.py · promo.py        (SQLAlchemy)
├── schemas/                cv · ai · billing · promo          (Pydantic request/response)
├── services/
│   ├── stripe_service.py   Webhook verification and handling
│   └── ai/                 base.py (clients) · improvement.py · ats.py · cover_letter.py
│                           translation.py (unused)
├── utils/sanitizer.py      mask_cv_pii — redact contact details before LLM calls
└── scripts/upgrade_user.py CLI: grant Pro manually

migrations/                 Alembic env + 2 revisions
test/                       pytest suite (2 tests)
create_promo.py             CLI: create a promo code
testDB.py, test_get_cv.py   Ad-hoc debugging scripts (not part of the test suite)
Dockerfile, docker-compose.yml
GEMINI.md                   Context file for the Gemini CLI agent
```

Layering is conventional: **router → (service) → model**. Only AI and the Stripe webhook have a
service layer; the CV, user, billing and promo routers query the database directly.

## Request lifecycle

1. **CORS** (`main.py`) — allowed origins are `FRONTEND_URL` plus `localhost`, `127.0.0.1` and
   `[::1]` on port 4321; credentials, all methods and all headers allowed.
2. **Routing** — every router is mounted under `/api/v1`. `/health` is the only route outside it.
3. **Authentication** — `HTTPBearer` extracts the token; `get_current_user_id`
   (`core/security.py`) decodes it and returns the `sub` claim (the Clerk user id).
4. **User bootstrap** — `get_current_user` (`api/dependencies.py`) loads the `users` row, creates
   it if missing (`is_pro=False`), and if `pro_expires_at` is in the past flips `is_pro` to `False`.
   It returns the user **id string**, not the ORM object.
5. **Handler** — runs with an `AsyncSession` from `get_db`. Sessions are per-request and are not
   auto-committed; each handler calls `await db.commit()` itself.
6. **Response** — serialised through the route's `response_model` where one is declared.

There are two `get_db` functions (`db/database.py` and `api/dependencies.py`). Routers import the
one in `api/dependencies.py`, and that is the one tests override.

## Configuration (`src/core/config.py`)

`Settings` reads environment variables, falling back to a `.env` file in the working directory.
Unknown variables are ignored.

| Variable | Required | Default | Used for |
| :--- | :---: | :--- | :--- |
| `DATABASE_URL` | ✅ | — | Postgres DSN. `postgres://` and `postgresql://` are rewritten to `postgresql+asyncpg://` |
| `ENVIRONMENT` | | `development` | `production` disables `/docs`, `/redoc`, `/openapi.json` |
| `FRONTEND_URL` | | `http://localhost:4321` | CORS origin and Stripe success/cancel URLs |
| `OPENAI_API_KEY` | for AI | — | All AI features |
| `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL` | | — / `https://api.deepseek.com` | Client is built but never selected |
| `STRIPE_API_KEY` | for checkout | — | Creating Checkout sessions |
| `STRIPE_WEBHOOK_SECRET` | for webhook | — | Verifying Stripe webhook signatures |
| `STRIPE_PRICE_7D`, `STRIPE_PRICE_30D`, `STRIPE_PRICE_LIFETIME` | for checkout | — | Stripe price ids per plan |
| `CLERK_API_KEY` | | — | **Declared but not read anywhere** |
| `PROJECT_NAME` | | `CV Studio Tools API` | OpenAPI title, `/health` |

`settings = Settings()` is evaluated at import time, so importing anything from `src` without
`DATABASE_URL` set raises a validation error. This includes the test suite and Alembic.

## Database schema

Three tables, defined in `src/models/`.

### `users`

| Column | Type | Notes |
| :--- | :--- | :--- |
| `id` | `String` PK | The Clerk user id (`user_…`) |
| `email` | `String`, unique, nullable | **Never populated by the application** |
| `is_pro` | `Boolean`, default `False` | |
| `pro_expires_at` | `DateTime(tz)`, nullable | `NULL` while Pro = lifetime; `NULL` while not Pro = n/a |
| `created_at` / `updated_at` | `DateTime(tz)` | `updated_at` has `onupdate` only, so it is `NULL` until first update |

### `cvs`

| Column | Type | Notes |
| :--- | :--- | :--- |
| `id` | `UUID` PK, default `uuid4` | Generated server-side |
| `user_id` | `String` FK → `users.id`, indexed | No `ON DELETE` rule |
| `title` | `String`, not null | |
| `content` | `JSONB`, not null | Opaque to the backend — the frontend's `CVData` object, or `{ "mode": "markdown", "markdown": "…" }` |
| `language` | `String`, server default `'ES'` | `ES` / `EN` / `PT` by convention; not validated |
| `created_at` / `updated_at` | `DateTime(tz)` | |

### `promo_codes`

| Column | Type | Notes |
| :--- | :--- | :--- |
| `id` | `UUID` PK | |
| `code` | `String`, unique, indexed | Case-sensitive |
| `max_uses` | `Integer`, default 1 | |
| `used_count` | `Integer`, default 0 | |
| `granted_days` | `Integer`, default 30 | `9999` or more means lifetime |
| `is_active` | `Boolean`, default `True` | |
| `created_at` | `DateTime(tz)` | |

There is no table recording *who* redeemed a code or *which* payments were processed.

The CV document's shape is owned by the frontend; see `docs/data-model.md` in the `cvstudio-tools`
repo. The only keys the backend ever looks inside are `personal.*` (PII masking and the cover-letter
header).

## External services

| Service | Direction | Where |
| :--- | :--- | :--- |
| Clerk | inbound JWTs; inbound webhook (`user.deleted`) | `core/security.py`, `routers/webhooks.py` |
| Stripe | outbound Checkout session creation; inbound webhook | `routers/billing.py`, `services/stripe_service.py` |
| OpenAI | outbound chat completions (`gpt-4o-mini`) | `services/ai/*` |

## Logging

There is no logging configuration. The engine is created with `echo=True`, so every SQL statement
is written to stdout, and the AI code uses `print("DEBUG: …")` statements.
