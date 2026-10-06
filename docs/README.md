# CVStudio.tools Backend — Knowledge Base

Reference documentation for `cvstudio-tools-backend`, the API behind **CVStudio.tools**.

> Describes the code as of the `fix/known-issues` branch (October 2026). If the code has moved on,
> trust the code and update the page.

## What this service is

A small FastAPI application that does four things for the frontend:

1. **Stores CVs** — CRUD over a PostgreSQL `cvs` table, one JSON document per CV.
2. **Tracks who is Pro** — a `users` row per Clerk user, with `is_pro` and an optional expiry.
3. **Sells Pro** — creates Stripe Checkout sessions, receives Stripe webhooks, redeems promo codes.
4. **Runs the AI features** — calls OpenAI for CV rewriting, ATS simulation and cover letters.

It has no UI, no background jobs and no cache. Everything is request/response.

The frontend lives in the sibling repo `cvstudio-tools` (Astro + React) and has its own `docs/`
folder. It calls this API directly from the browser with a Clerk session token.

## Pages

| Page | Read it when you need to… |
| :--- | :--- |
| [architecture.md](./architecture.md) | Understand the layout, request lifecycle, configuration and database schema |
| [api-reference.md](./api-reference.md) | Know exactly what each endpoint accepts, returns and rejects |
| [auth-plans-billing.md](./auth-plans-billing.md) | Work on authentication, the Pro lifecycle, Stripe or promo codes |
| [ai-services.md](./ai-services.md) | Change prompts, models, PII masking, rate limits or the AI endpoints |
| [development.md](./development.md) | Run it locally, migrate the database, test, deploy, or use the admin scripts |
| [known-issues.md](./known-issues.md) | See what is still open and what to watch out for |

## Thirty-second mental model

```
Browser ── Bearer <Clerk JWT> ──▶ FastAPI  /api/v1
                                   │
         get_current_user_obj ─────┤  verify token (Clerk JWKS) → user id → ensure users row
                                   │  → expire Pro if due
      ┌────────────┬───────────────┼────────────────┬───────────────┐
   /cvs          /users/me       /ai/*           /billing/*       /promo/*
   CRUD          is_pro          Pro + quota     Stripe Checkout   redeem code
      │                            │                 │
  PostgreSQL                    OpenAI            Stripe ──webhook──▶ /webhooks/stripe ──▶ grant / revoke Pro
  (Alembic-managed)                              Clerk ───webhook──▶ /webhooks/clerk  ──▶ sync email, delete user data
```

## The three facts that matter most

- **Identity comes from Clerk and is verified here.** Session tokens are checked against the Clerk
  instance named by `CLERK_ISSUER`; the service refuses to start without that setting. Webhooks
  from Clerk and Stripe are signature-checked.
- **Pro is a row, not a subscription.** `users.is_pro` plus `users.pro_expires_at` (null = lifetime).
  Every grant goes through `src/services/pro.py`; expiry is applied lazily on the user's next request.
- **Alembic owns the schema.** The app no longer creates tables at startup; the container runs
  `alembic upgrade head` before serving. Every model change needs a migration.
