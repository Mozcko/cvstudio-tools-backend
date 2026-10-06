# CVStudio.tools Backend — Knowledge Base

Reference documentation for `cvstudio-tools-backend`, the API behind **CVStudio.tools**.

> Written against commit `e0f98e4` (`main`, 2026-06-19). If the code has moved on, trust the code
> and update the page.

## What this service is

A small FastAPI application (about 900 lines of Python) that does four things for the frontend:

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
| [ai-services.md](./ai-services.md) | Change prompts, models, PII masking or the AI endpoints |
| [development.md](./development.md) | Run it locally, migrate the database, test, deploy, or use the admin scripts |
| [known-issues.md](./known-issues.md) | See the bugs and traps found while documenting — **read this first** |

## Thirty-second mental model

```
Browser ── Bearer <Clerk JWT> ──▶ FastAPI  /api/v1
                                   │
             get_current_user ─────┤  decode token → user id → ensure users row → expire Pro if due
                                   │
      ┌────────────┬───────────────┼────────────────┬───────────────┐
   /cvs          /users/me       /ai/*           /billing/*       /promo/*
   CRUD          is_pro          Pro only        Stripe Checkout   redeem code
      │                            │                 │
  PostgreSQL                    OpenAI            Stripe ──webhook──▶ /webhooks/stripe ──▶ is_pro = true
  (users, cvs, promo_codes)   gpt-4o-mini
                                                 Clerk ───webhook──▶ /webhooks/clerk  ──▶ delete user data
```

## The three facts that matter most

- **Identity comes from Clerk.** The user id is the `sub` claim of the Clerk session token; a
  `users` row is created the first time an id is seen.
- **Pro is a row, not a subscription.** `users.is_pro` plus `users.pro_expires_at` (null = lifetime).
  Expiry is applied lazily, the next time that user makes an authenticated request.
- **Tables are created by the app, not by Alembic.** `Base.metadata.create_all` runs on startup; the
  migration history is incomplete. See [development.md](./development.md#database-and-migrations).
