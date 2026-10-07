# CV Studio Tools Backend — notes for AI coding agents

FastAPI service behind CVStudio.tools: CV storage, Pro access, Stripe billing and AI features.
The full, maintained documentation is in [`docs/`](./docs/README.md); read
[`CONTRIBUTING.md`](./CONTRIBUTING.md) before changing anything. This file only lists the rules
that are easy to get wrong.

## Commands

```bash
make up        # run locally (Docker); API on :8000
make check     # lint, format check, tests with coverage, migration checks: must pass before a PR
make format    # apply ruff fixes and formatting
make migration m="describe the change"   # create an Alembic migration from model changes
```

## Rules

- **Alembic owns the schema.** The app does not create tables at startup. Every model change needs
  a migration, and new model modules must be imported in `src/models/__init__.py`.
- **Pro access is changed only in `src/services/pro.py`** (`grant_pro`, `revoke_grant`).
- **Authentication:** use `get_current_user` / `get_current_user_obj` from `src/api/dependencies.py`;
  scope every query to that user. Tokens are verified in `src/core/security.py`.
- **AI endpoints:** mask personal data with `mask_cv_pii` before calling the model, guard the route
  with `enforce_ai_quota`, and put user-supplied text in the user message, never the system prompt.
- **Errors and logs:** return user-facing messages, log the technical cause. Never log or report CV
  content, job descriptions, emails or tokens.
- **Tests never call Clerk, Stripe or OpenAI.** Use the fakes and fixtures in `test/`. Coverage must
  stay above the minimum in `pyproject.toml`.
- **Secrets:** nothing secret-shaped in code or tests, even as a placeholder; generate test values
  (`test/fakes.py`). The repository is public.
- Dependencies are pinned in `requirements.txt` (runtime) and `requirements-dev.txt` (tools).
