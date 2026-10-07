# CV Studio Tools Backend

[![CI](https://github.com/Mozcko/cvstudio-tools-backend/actions/workflows/ci.yml/badge.svg)](https://github.com/Mozcko/cvstudio-tools-backend/actions/workflows/ci.yml)
[![Security](https://github.com/Mozcko/cvstudio-tools-backend/actions/workflows/security.yml/badge.svg)](https://github.com/Mozcko/cvstudio-tools-backend/actions/workflows/security.yml)

The API behind [CVStudio.tools](https://www.cvstudio.tools): it stores CVs, tracks Pro access, sells
it through Stripe, and runs the AI features (rewrite, ATS simulation, cover letters).

> **Documentation:** [`docs/`](./docs/README.md) · **Contributing:** [`CONTRIBUTING.md`](./CONTRIBUTING.md) · **Security:** [`SECURITY.md`](./SECURITY.md)

The frontend lives in [`Mozcko/cvstudio-tools`](https://github.com/Mozcko/cvstudio-tools).

## Stack

FastAPI · PostgreSQL with SQLAlchemy (async) and Alembic · Clerk for authentication · Stripe for
payments · OpenAI for the AI features · Docker · deployed on Railway.

## Quick start

You need Docker (or Podman) and `make`.

```bash
cp .env.example .env     # set CLERK_ISSUER at least; the service will not start without it
make up                  # API on http://localhost:8000, Swagger UI at /docs
make check               # lint, format, tests and migration checks, exactly as CI runs them
```

`make help` lists every task. Setup details, environment variables, migrations, tests and
deployment are in [`docs/development.md`](./docs/development.md).

## Where things are

| Path | What |
| :--- | :--- |
| `src/api/routers/` | Endpoints: CVs, users, AI, billing, promo codes, webhooks |
| `src/services/` | Pro access rules, Stripe handling, AI prompts |
| `src/core/` | Settings, token verification, error reporting |
| `src/models/`, `migrations/` | Database models and the Alembic migrations that own the schema |
| `test/` | pytest suite (needs PostgreSQL; `make test` provides it) |
| `docs/` | Architecture, API reference, auth and billing, AI, development, known issues |

All endpoints are under `/api/v1` and need a Clerk session token; see
[`docs/api-reference.md`](./docs/api-reference.md).

## Licence

Copyright © 2026 Joaquín Eduardo Ramos Farfán. All rights reserved. The code is public to read;
it is not licensed for reuse. See [`LICENSE`](./LICENSE).
