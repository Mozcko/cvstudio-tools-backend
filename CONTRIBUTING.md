# Contributing

Thanks for working on the CVStudio.tools backend. This page is the practical guide: how to set up,
what a change needs before it can be merged, and how it reaches production. For how the code works,
read [`docs/`](./docs/README.md).

## Quick start

You need Docker (or Podman) and `make`. Nothing else has to be installed on your machine.

```bash
cp .env.example .env     # set CLERK_ISSUER at least — the service will not start without it
make up                  # API on http://localhost:8000, Swagger UI at /docs
make check               # everything CI checks: lint, format, tests, migrations
```

`make help` lists every task. With Podman: `make COMPOSE="podman compose" check`.

## Workflow

1. **Branch from `main`.** Name it `feat/…`, `fix/…`, `chore/…` or `docs/…`, with an issue number
   when there is one: `fix/42-promo-double-redeem`.
2. **Make the change, with tests.** See [What a change needs](#what-a-change-needs).
3. **Run `make check`** until it is green.
4. **Open a pull request to `main`.** Fill in the template. CI runs automatically.
5. **Merge when CI is green.** `main` is protected: a pull request and a passing
   `✅ CI passed` check are required. Prefer *Squash and merge* so `main` has one commit per change.
6. **Deployment** starts on its own after the merge — see [Deployment](#deployment).

Keep pull requests small and about one thing. A refactor and a behaviour change are two pull
requests.

### Commit messages

A short imperative summary, optionally prefixed with the area, and a body when the *why* is not
obvious:

```
billing: apply a checkout session only once

Stripe retries webhook deliveries; the session id is now the idempotency key.
```

Never put secrets, tokens, personal data or exploit details in a commit message — this repository
is public.

## What a change needs

| If you change… | You also need… |
| :--- | :--- |
| Any behaviour | A test. For a bug fix, one that fails without the fix |
| A model (`src/models/`) | A migration: `make migration m="add x to y"`, then **read the generated file**. New model modules must be imported in `src/models/__init__.py` |
| A request or response | The Pydantic schema, `docs/api-reference.md`, and the frontend's `src/lib/api.ts` |
| A setting | `src/core/config.py`, `.env.example`, `docs/architecture.md`, and the deployment checklist (`PROD-ENV-CHECKLIST.md` in the frontend repo) |
| How Pro is granted or revoked | Only `src/services/pro.py`, with tests in `test/test_pro.py` |
| An AI feature | Mask personal data first (`mask_cv_pii`), guard the route with `enforce_ai_quota`, test with a fake client |
| A dependency | Pin the exact version in `requirements.txt` (runtime) or `requirements-dev.txt` (tools) and run `make audit` |

### Tests

```bash
make test                              # all tests with coverage
make test ARGS="test/test_ai.py -k rate_limit -x"   # a subset
```

- Tests run against a throwaway PostgreSQL database (`cvstudio_test`) that is **wiped for every
  test**. `make test` creates it; never point `DATABASE_URL` at a database you care about.
- External services are always faked: no test may call Clerk, Stripe or OpenAI.
  `test/conftest.py` has the fixtures (`client`, `db`, `current_user`); `test/test_ai.py` and
  `test/test_billing_promo.py` show the patterns for fakes.
- Coverage must stay at or above the minimum in `pyproject.toml` (95%). Do not lower it to get a
  pull request through; add the missing test.

### Style

`ruff` lints and formats the code (configuration in `pyproject.toml`).

```bash
make lint      # check, as CI does
make format    # fix and format
```

Optional: `pip install pre-commit && pre-commit install` runs the same checks before each commit.

Conventions the linter cannot enforce:

- Routes declare a `response_model`, so database columns are never returned by accident.
- Every query is scoped to the authenticated user; `404` for missing, `403` for someone else's.
- Errors returned to clients are written for users. Log the technical cause; do not return it.
- Do not log CV content, job descriptions, emails or tokens.

### Migrations

Alembic owns the schema; the application never creates or alters tables.

```bash
make migration m="add theme to cvs"   # autogenerate from the models
make migrations-check                  # upgrade, compare with models, downgrade, upgrade again
make migrate                           # apply to your development database
```

Migrations must work on a database that already contains data, and `downgrade()` must undo
`upgrade()`. A migration that is already on `main` is never edited — add a new one.

## Continuous integration

Every pull request and every push to `main` runs [`.github/workflows/ci.yml`](.github/workflows/ci.yml):

| Job | Fails when |
| :--- | :--- |
| 🧹 Lint & Format | `ruff check` or `ruff format --check` report anything |
| 🧪 Tests & Coverage | a test fails, a database test is skipped, or coverage is below the minimum |
| 🗄️ Migrations | there is more than one head, an empty database cannot be upgraded, models and migrations disagree, or downgrade/upgrade does not round-trip |
| 🐳 Docker Image | the production image does not build, contains test tools, or does not start and answer `/health` |
| 🔒 Dependency Audit | a runtime dependency has a known vulnerability |
| ✅ CI passed | any of the above did not succeed — this is the check required to merge |

[`security.yml`](.github/workflows/security.yml) adds CodeQL analysis on every pull request and a
weekly dependency audit. Dependabot opens update pull requests weekly.

A red check is information, not an obstacle: read the job log, reproduce it with the matching
`make` target, fix the cause.

## Deployment

Production runs on Railway. [`.github/workflows/deploy.yml`](.github/workflows/deploy.yml) deploys
`main` after CI has passed:

```
merge to main ─▶ CI ─▶ Deploy: approval (production environment) ─▶ railway up ─▶ /health smoke test
```

- The container runs `scripts/start.sh`: database migrations first, then the server. A failed
  migration stops the release before it serves traffic.
- The deploy job waits for approval from a reviewer of the `production` environment.
- After the upload, the workflow polls `BACKEND_URL/health` for up to five minutes and fails if the
  service does not come up.
- **Manual deploy or rollback:** *Actions → Deploy → Run workflow* and enter the commit or tag to
  deploy. Rolling back code does not roll back migrations; if the previous release cannot run on
  the new schema, write a forward fix instead.

### One-time setup (maintainers)

| Where | What |
| :--- | :--- |
| Railway → project → Settings → Tokens | Create a **project token** for the production environment |
| GitHub → Settings → Secrets and variables → Actions → *Secrets* | `RAILWAY_TOKEN` = that token |
| … → *Variables* | `RAILWAY_SERVICE` = the backend service's name or id; `BACKEND_URL` = its public URL, e.g. `https://api.cvstudio.tools` |
| GitHub → Settings → Environments → `production` | Required reviewers (who may approve a deploy) |
| Railway → service → Settings → Source | **Disable automatic deploys** from GitHub, otherwise every commit is deployed twice |
| GitHub → Settings → Code security | Enable *Private vulnerability reporting* (used by `SECURITY.md`) and *Secret scanning* with push protection |

Until `RAILWAY_TOKEN` and `RAILWAY_SERVICE` exist, the deploy workflow skips itself with a warning.

The environment variables the service itself needs are listed in `docs/architecture.md` and in
`PROD-ENV-CHECKLIST.md` in the frontend repository.

## Reporting bugs and security problems

- Bugs and ideas: open an issue with the matching template.
- Security problems: **never in a public issue.** Follow [`SECURITY.md`](./SECURITY.md).
