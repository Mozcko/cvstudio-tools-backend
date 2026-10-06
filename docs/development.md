# Development

## Local layout

```
cvstudio/
├── cvstudio-tools/            frontend (Astro)    http://localhost:4321
└── cvstudio-tools-backend/    this repo (FastAPI) http://localhost:8000
```

Two independent git repositories side by side.

## Running with Docker (recommended)

```bash
cp .env.example .env          # fill in at least CLERK_ISSUER — see below
docker compose up --build
```

- `api` — built from `Dockerfile` (Python 3.11). In Compose it runs
  `alembic upgrade head && uvicorn … --reload` on port **8000**; the repo is bind-mounted at `/app`,
  so code edits reload live and the container reads your `.env`.
- `db` — `postgres:15-alpine` on port **5432**, user/password `postgres`/`postgres`, database
  `cvstudio`, data in the `postgres_data` volume.

`docker-compose.yml` only overrides `DATABASE_URL` (to reach the `db` service); every other
setting comes from the mounted `.env` file.

Check it is up:

```bash
curl http://localhost:8000/health          # {"status":"healthy",…}
# Swagger UI: http://localhost:8000/docs
```

Podman works the same way (`podman compose …`, or `podman build` + `podman run`).

## Running without Docker

```bash
python3.11 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
# needs a PostgreSQL reachable at DATABASE_URL
alembic upgrade head
uvicorn src.main:app --reload
```

Use Python 3.11 or 3.12. The pinned versions (`asyncpg 0.29`, `pydantic-settings 2.3`) predate
newer interpreters and may not install on them.

Run commands from the repo root: imports are absolute from `src.` and `.env` is resolved relative to
the working directory.

## Environment variables

The process will not start without `DATABASE_URL` and `CLERK_ISSUER`. Everything else only breaks
the feature that needs it. Full table in
[architecture.md](./architecture.md#configuration-srccoreconfigpy).

| To exercise… | You need |
| :--- | :--- |
| Any authenticated endpoint | `CLERK_ISSUER` — your Clerk instance's Frontend API URL, the same instance the frontend's `PUBLIC_CLERK_PUBLISHABLE_KEY` belongs to |
| CV CRUD, `/users/me`, promo codes | nothing more |
| AI endpoints | `OPENAI_API_KEY`, and a Pro user |
| Checkout | `STRIPE_API_KEY` and the three `STRIPE_PRICE_*` |
| Stripe webhook | `STRIPE_WEBHOOK_SECRET` (`stripe listen` prints one) |
| Clerk webhook | `CLERK_WEBHOOK_SECRET` (and a tunnel so Clerk can reach your machine) |

To call the API by hand you need a real Clerk session token; the easiest source is the browser's
network tab while using the frontend. Tokens are short-lived (about a minute).

## Database and migrations

**Alembic owns the schema.** The application does not create or alter tables.

```bash
alembic upgrade head                              # apply
alembic revision --autogenerate -m "add x to y"   # create, then review the file
alembic check                                     # fails if models and migrations disagree
docker compose exec api alembic upgrade head      # inside Docker
```

`migrations/env.py` reads `settings.DATABASE_URL` and imports `src.models`, whose `__init__` imports
every model module — add new model files there or autogenerate will not see them.

Revision history:

| Revision | What it does |
| :--- | :--- |
| `c19b7a9812e7` | Baseline: creates `users`, `cvs`, `promo_codes` **if they do not exist** |
| `9db7771a15bc` | Adds `users.pro_expires_at` **if missing** |
| `a4d2f7c1b9e3` | `cvs.theme`; `cvs.user_id` cascades; `promo_redemptions`, `payments`, `ai_requests` |

The first two are guarded because databases created before this point were built by the
application itself (`create_all`) and may or may not carry an `alembic_version` row. With the
guards, `alembic upgrade head` is correct on an empty database, on such a pre-existing database,
and on one that was already stamped. New revisions should not need guards.

Where migrations run:

- **Production:** `scripts/start.sh` (the image's `CMD`) runs `alembic upgrade head` and then
  starts Uvicorn. A failed migration stops the container before it serves traffic.
- **Compose:** the `command` does the same, with `--reload`.
- **Tests:** build the schema from the models (`Base.metadata.create_all`) on a scratch database.

## Tests

The suite needs a PostgreSQL it may wipe (the models use `JSONB` and `UUID`). Tests drop and
recreate all tables for every test, so **point it at a throwaway database, never a real one.**

With Docker Compose:

```bash
docker compose up -d db
docker compose exec db psql -U postgres -c "CREATE DATABASE cvstudio_test"
docker compose run --rm \
  -e DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/cvstudio_test \
  api pytest
```

Locally, `test/conftest.py` defaults to
`postgresql+asyncpg://postgres:postgres@localhost:5432/cvstudio_test` and supplies dummy values for
the other required settings. If the database is unreachable the database-backed tests are skipped,
not failed — check the summary line.

| File | Covers |
| :--- | :--- |
| `test_security.py` | Token verification: valid; wrong key, expired, wrong issuer, wrong origin, no subject, wrong algorithm, unsigned, garbage |
| `test_webhooks.py` | Clerk webhook: unsigned / wrong secret / tampered body rejected; `user.deleted` purges; `user.created` stores the email |
| `test_pro.py` | `grant_pro`, `revoke_grant`, `apply_expiry` date arithmetic |
| `test_billing_promo.py` | Stripe webhook (signature, idempotency, extension, unpaid, refund); checkout errors; promo redemption rules |
| `test_cvs_users.py` | `/users/me`; CV CRUD with theme; ordering; ownership; free-tier limit |
| `test_ai.py` | Pro gate, PII masking and restore, job description isolation, 502 on provider failure, rate limit, legacy shim, cover letter, ATS |
| `test_sanitizer.py` | Masking and restoring in isolation |

Patterns worth copying (`test/conftest.py`):

- `client` — an `httpx.AsyncClient` on the ASGI app with `get_db` and `get_current_user_id`
  overridden. Switch user with the `current_user` fixture: `current_user["id"] = "user_other"`.
- `db` — a session on the same scratch database, for arranging and asserting.
- External services are faked, never called: `FakeOpenAI` in `test_ai.py`,
  `stripe.Webhook.construct_event` monkeypatched in `test_billing_promo.py`, a local RSA key in
  `test_security.py`, real Svix signing in `test_webhooks.py`.

CI (`.github/workflows/ci.yml`) runs the suite against a PostgreSQL service, then applies the
migrations to an empty database and runs `alembic check`.

## Admin scripts

Run from the repo root (or `docker compose exec api …`).

```bash
# Grant Pro by Clerk user id: lifetime, or a number of days added to what they have
python src/scripts/upgrade_user.py --user-id user_2abc…
python src/scripts/upgrade_user.py --user-id user_2abc… --days 30
python src/scripts/upgrade_user.py --email jane@example.com --days 7   # once Clerk has synced the email

# Create a promo code (--uses 0 = unlimited, --days 9999 = lifetime)
python create_promo.py --code LAUNCH30 --uses 100 --days 30
```

Useful SQL (`docker compose exec db psql -U postgres cvstudio`):

```sql
SELECT id, email, is_pro, pro_expires_at FROM users;
SELECT id, user_id, title, language, theme, updated_at FROM cvs ORDER BY updated_at DESC;
SELECT code, used_count, max_uses, granted_days, is_active FROM promo_codes;
SELECT session_id, user_id, plan, created_at, refunded_at FROM payments ORDER BY created_at DESC;
SELECT user_id, count(*) FROM ai_requests WHERE created_at > now() - interval '1 day' GROUP BY 1;
```

## Deployment

Target is Railway, alongside the frontend, built from `Dockerfile`. The variable checklist and
deployment order are in `PROD-ENV-CHECKLIST.md` in the **frontend** repo.

- The image's `CMD` is `scripts/start.sh`: migrate, then `uvicorn` without `--reload` on `$PORT`
  (default 8000).
- Set `ENVIRONMENT=production` to hide `/docs`, `/redoc` and `/openapi.json`.
- Set `FRONTEND_URL` to the real origin — it controls CORS, the accepted token origin and Stripe's
  return URLs.
- `CLERK_ISSUER` must be set **before** the first deploy of this version, or the service will not
  start. That is deliberate.
- `DATABASE_URL` may be given as `postgres://…` or `postgresql://…`; it is rewritten for asyncpg.
- Register the Clerk and Stripe webhooks listed in
  [auth-plans-billing.md](./auth-plans-billing.md).
- Health check path: `/health`.

## Recipes

### Add an endpoint

1. Request/response models in `src/schemas/` (always a `response_model`, so internal columns are
   not leaked).
2. Route in the relevant file under `src/api/routers/`, with
   `user_id: str = Depends(get_current_user)` (or `user: User = Depends(get_current_user_obj)`)
   and `db: AsyncSession = Depends(get_db)`.
3. Scope every query by the user; return `404` for missing and `403` for someone else's resource,
   as `cv.py` does.
4. New router file → `app.include_router(…, prefix="/api/v1")` in `src/main.py`.
5. A test using the `client` fixture.
6. Add the client method to the frontend's `src/lib/api.ts`.

### Add a column or table

Model → `alembic revision --autogenerate` → review → Pydantic schema (if it should be accepted or
returned) → `alembic check` → frontend types. Fields missing from a schema are silently dropped on
input and omitted on output. New model files must be imported in `src/models/__init__.py`.

### Make a route Pro-only

`user: User = Depends(require_pro)`. For anything that calls a paid provider, use
`Depends(enforce_ai_quota)` instead so it is rate-limited too.

### Change how Pro is granted

Only in `src/services/pro.py`, with tests in `test/test_pro.py`. Do not set `is_pro` or
`pro_expires_at` anywhere else.
