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
cp .env.example .env          # fill in what you need — see below
docker compose up --build
```

- `api` — built from `Dockerfile` (Python 3.11), served by Uvicorn with `--reload` on port **8000**.
  The repo is bind-mounted at `/app`, so code edits reload live and the container reads your `.env`.
- `db` — `postgres:15-alpine` on port **5432**, user/password `postgres`/`postgres`, database
  `cvstudio`, data in the `postgres_data` volume.

`docker-compose.yml` overrides `DATABASE_URL` to point at the `db` service. The other variables it
lists are passed from your shell; anything else (`OPENAI_API_KEY`, the Stripe price ids,
`FRONTEND_URL`) reaches the app through the mounted `.env` file.

Check it is up:

```bash
curl http://localhost:8000/health          # {"status":"healthy",…}
# Swagger UI: http://localhost:8000/docs
```

## Running without Docker

```bash
python3.11 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
# needs a PostgreSQL reachable at DATABASE_URL
uvicorn src.main:app --reload
```

Use Python 3.11 or 3.12. The pinned versions (`asyncpg 0.29`, `pydantic-settings 2.3`) predate
newer interpreters and may not install on them.

Run commands from the repo root: imports are absolute from `src.` and `.env` is resolved relative to
the working directory.

## Environment variables

Minimum to boot: `DATABASE_URL`. Everything else is optional and only breaks the feature that needs
it. Full table in [architecture.md](./architecture.md#configuration-srccoreconfigpy).

| To exercise… | You need |
| :--- | :--- |
| CV CRUD, `/users/me`, promo codes | `DATABASE_URL` only |
| AI endpoints | `OPENAI_API_KEY`, and a Pro user |
| Checkout | `STRIPE_API_KEY` and the three `STRIPE_PRICE_*` |
| Stripe webhook | `STRIPE_WEBHOOK_SECRET` |

`.env.example` omits `ENVIRONMENT` and the three `STRIPE_PRICE_*` variables; add them by hand.

To call the API by hand you need a Clerk session token; the easiest source is the browser's
network tab while using the frontend.

## Database and migrations

Tables are created by the application: the `lifespan` hook in `src/main.py` runs
`Base.metadata.create_all` on every startup. That creates missing **tables** but never alters
existing ones.

Alembic is wired up (`alembic.ini`, async `migrations/env.py` reading `settings.DATABASE_URL`) but
its history does not describe the schema:

| Revision | What it does |
| :--- | :--- |
| `c19b7a9812e7` "Add promo codes table" | Nothing — `upgrade()` is `pass` |
| `9db7771a15bc` "Add pro_expires_at to User" | `ALTER TABLE users ADD COLUMN pro_expires_at` |

There is no baseline revision creating `users`, `cvs` or `promo_codes`. As a result:

- On an **empty** database, `alembic upgrade head` fails (no `users` table).
- On a database the app has already started against, `create_all` has built `users` with
  `pro_expires_at` included, so `alembic upgrade head` fails on the duplicate column.
- It only works on a database created *before* `pro_expires_at` existed.

Practical rules until this is repaired:

- **Fresh environment:** start the app once, then `alembic stamp head`.
- **Adding a column to an existing table:** `create_all` will not do it. Write a migration
  (`alembic revision --autogenerate -m "…"`), review it, and run `alembic upgrade head` against
  every environment.
- **Adding a table:** import the model in `src/main.py` and `migrations/env.py` so it registers
  with `Base`; `create_all` will create it, and a migration should still be written.

Inside Docker: `docker compose exec api alembic upgrade head`.

## Tests

```bash
DATABASE_URL=postgresql+asyncpg://x:x@localhost/x pytest
```

`pytest.ini` sets `asyncio_mode = auto` and `testpaths = test`. `DATABASE_URL` must be set (any
syntactically valid value) because settings load at import; no database connection is made.

| Test | Covers |
| :--- | :--- |
| `test/test_sanitizer.py` | `mask_cv_pii` redacts email, phone, city, social URLs; leaves the rest; does not mutate input |
| `test/test_webhooks.py` | `POST /webhooks/clerk` with `user.deleted` returns 200 and calls `execute` + `commit` on a mocked session |

Pattern for API tests: `httpx.AsyncClient(transport=ASGITransport(app=app))` plus
`app.dependency_overrides[get_db]` (the `get_db` from `src.api.dependencies`). Override
`get_current_user` the same way to test authenticated routes.

Nothing else is covered: no tests for CV CRUD, the free-tier limit, Pro expiry, checkout, the Stripe
webhook, promo redemption or the AI services.

`testDB.py` and `test_get_cv.py` in the repo root are one-off debugging scripts (one has a
hardcoded CV id). They are outside `testpaths` and are not tests.

This repo has no CI workflow of its own. The frontend repo's `.github/workflows/ci.yml` contains a
"Backend QA" job that expects both projects checked out as sibling directories.

## Admin scripts

Run from the repo root (or `docker compose exec api …`).

```bash
# Grant Pro by Clerk user id (find it in the Clerk dashboard, or in the users table)
python src/scripts/upgrade_user.py --user-id user_2abc…

# Create a promo code
python create_promo.py --code LAUNCH30 --uses 100 --days 30
```

`upgrade_user.py --email …` does not work in practice: the `email` column is never populated, and
for an unknown email it tries to insert a user with no id.

Useful SQL (`docker compose exec db psql -U postgres cvstudio`):

```sql
SELECT id, is_pro, pro_expires_at FROM users;
SELECT id, user_id, title, language, updated_at FROM cvs ORDER BY updated_at DESC;
SELECT code, used_count, max_uses, granted_days, is_active FROM promo_codes;
```

## Deployment

Target is Railway, alongside the frontend. The variable checklist is `PROD-ENV-CHECKLIST.md` in the
**frontend** repo. There is no Railway config file here; the service builds from `Dockerfile`.

Things that differ from that checklist — verify before relying on it:

| Checklist says | Code says |
| :--- | :--- |
| Stripe webhook at `/api/v1/billing/webhooks` | `/api/v1/webhooks/stripe` |
| Health check at `/api/v1/health` | `/health` |
| `CLERK_API_KEY` is required | Declared, never read |

Production notes:

- Set `ENVIRONMENT=production` to hide `/docs`, `/redoc` and `/openapi.json`.
- Set `FRONTEND_URL` to the real origin — it controls CORS and Stripe's return URLs.
- The image's `CMD` runs Uvicorn with `--reload` on a fixed port 8000; override the start command
  in production (no `--reload`, and bind to the platform's `$PORT` if it assigns one).
- `DATABASE_URL` may be given as `postgres://…` or `postgresql://…`; it is rewritten for asyncpg.
- Configure the Clerk webhook (`user.deleted` → `/api/v1/webhooks/clerk`) and the Stripe webhook.

## Recipes

### Add an endpoint

1. Request/response models in `src/schemas/`.
2. Route in the relevant file under `src/api/routers/`, with
   `user_id: str = Depends(get_current_user)` and `db: AsyncSession = Depends(get_db)`.
3. Scope every query by `user_id`; return `404` for missing and `403` for someone else's resource,
   as `cv.py` does.
4. New router file → `app.include_router(…, prefix="/api/v1")` in `src/main.py`.
5. Add the client method to the frontend's `src/lib/api.ts`.

### Add a column

Model → Alembic migration → Pydantic schema (if it should be accepted or returned) → frontend
types. Remember that fields missing from a schema are silently dropped on input and omitted on
output.

### Make a route Pro-only

Call `await check_pro_status(user_id, db)` from `routers/ai.py` (or move it to
`api/dependencies.py` and use it as a dependency) **outside** any broad `try/except`, so the `403`
is not converted to a `500`.
