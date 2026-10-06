## What and why

<!-- What does this change, and what problem does it solve? Link the issue: Closes #123 -->

## How it was tested

<!-- Commands you ran, cases you tried by hand, anything you could not test -->

## Checklist

- [ ] `make check` passes locally (lint, format, tests, migrations)
- [ ] New behaviour has tests; a bug fix has a test that failed before the fix
- [ ] Model changes come with an Alembic migration (`alembic check` is clean)
- [ ] API changes are reflected in `docs/api-reference.md` and in the frontend client
- [ ] New settings are in `.env.example`, `docs/architecture.md` and the deployment checklist
- [ ] No secrets, tokens or personal data in code, tests, logs or this description

## Deployment notes

<!-- New environment variables, webhooks to register, data to backfill, anything to do before or after deploying. "None" is a fine answer. -->
