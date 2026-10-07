# Authentication, Plans and Billing

## Authentication

The frontend signs users in with Clerk and sends the Clerk session JWT as a Bearer token.

### Token verification (`src/core/security.py`)

`decode_clerk_token` checks, in order:

1. **Signature** — RS256, against the key set published at
   `{CLERK_ISSUER}/.well-known/jwks.json` (fetched with `PyJWKClient`, cached).
2. **Required claims** — `exp`, `iat`, `sub`; expiry with 5 seconds of leeway.
3. **Issuer** — must equal `CLERK_ISSUER`.
4. **Authorized party** — if the token has an `azp` claim, it must be one of
   `settings.authorized_parties` (by default the CORS origins: `FRONTEND_URL` plus localhost).

Any failure is a `401`; an unreachable key set is a `503`. `CLERK_ISSUER` is a required setting, so
a deployment without it fails at startup rather than running unauthenticated.

`get_current_user_id` is a plain `def` on purpose: the key lookup is blocking I/O, and FastAPI runs
synchronous dependencies in its threadpool.

### Dependencies (`src/api/dependencies.py`)

| Dependency | Returns | Use for |
| :--- | :--- | :--- |
| `get_current_user_id` | `str` | Rarely — only when no user row is wanted |
| `get_current_user_obj` | `User` | Routes that need `is_pro` or other fields |
| `get_current_user` | `str` (the id) | Routes that only scope queries by user |
| `require_pro` | `User` | Pro-only routes (`403` otherwise) |
| `enforce_ai_quota` | `User` | AI routes: `require_pro` + rate limit + usage record |

`get_current_user_obj` is the base of the chain: it loads the `users` row, creates it on first
sight (tolerating a concurrent first request) and applies Pro expiry. Everything else builds on it,
so every authenticated route sees an up-to-date `is_pro`.

In tests, override `get_current_user_id` (and `get_db`) — see `test/conftest.py`.

### User records

There is no sign-up endpoint. A `users` row appears the first time a Clerk user id is seen, by
whichever runs first: an authenticated request, a Clerk `user.created` webhook, a Stripe webhook
for a not-yet-seen user, or `scripts/upgrade_user.py --user-id`.

`email` is filled in by the Clerk `user.created` / `user.updated` webhooks (the primary address).
It is informational: nothing authenticates by it. If the address is already attached to another
row the update is skipped and logged.

### Account deletion

The Clerk `user.deleted` webhook deletes the user row. `cvs`, `promo_redemptions` and
`ai_requests` reference `users.id` with `ON DELETE CASCADE`, so they go with it. `payments` rows
are kept on purpose (accounting), holding only the Clerk id.

### Clerk setup

- `CLERK_ISSUER` — the instance's **Frontend API URL** (Clerk Dashboard → API Keys), e.g.
  `https://your-app.clerk.accounts.dev` in development or `https://clerk.yourdomain.com` in
  production. Must be `https://`; a trailing slash is ignored.
- Webhook endpoint → `{backend}/api/v1/webhooks/clerk`, events `user.created`, `user.updated`,
  `user.deleted`; its signing secret goes in `CLERK_WEBHOOK_SECRET`.
- If the frontend is served from more than one origin, list them in `CLERK_AUTHORIZED_PARTIES`
  (comma-separated).

## The Pro lifecycle

State lives in two columns:

| `is_pro` | `pro_expires_at` | Meaning |
| :--- | :--- | :--- |
| `false` | `null` | Free |
| `true` | a future timestamp | Pro until then |
| `true` | `null` | Lifetime |
| `true` | a past timestamp | Expired but not yet noticed — becomes Free on the user's next request |

### Levels

There are two paid levels. **Pro** is what every paid plan gives. **Premium** is the extra level
for features with a real running cost (the voice mock interview): it comes with Active Hunt and
Lifetime, not with the Sprint Pass.

| Plan (`plan` in `/users/me`) | Bought as | Pro | Premium |
| :--- | :--- | :---: | :---: |
| `free` | — | | |
| `sprint` | plan `7` | 7 days | |
| `active` | plan `30` | 30 days | the same 30 days |
| `lifetime` | plan `lifetime` | for ever | for ever |

Premium is one more column, `users.premium_until`. A user is premium when they are lifetime, or
`premium_until` is in the future. It always lies inside the Pro period, so mixed purchases work
out naturally: Active Hunt then a Sprint Pass gives 37 days of Pro of which the first 30 are
premium. `PLAN_GRANTS` in `src/services/pro.py` is the single table of what each plan grants.
Promo codes carry their own `premium` flag (lifetime codes are always premium).

All changes go through `src/services/pro.py`:

| Function | Behaviour |
| :--- | :--- |
| `apply_expiry(user)` | Downgrades a user whose time has run out |
| `grant_pro(user, days, premium=False)` | `days=None` or `≥ 9999` → lifetime. Otherwise **adds** the days to the remaining time (or starts from now). Never shortens access and never downgrades lifetime |
| `revoke_grant(user, days, premium=False)` | Undoes one grant: lifetime → Free; timed → subtract the days (and downgrade if that leaves none). A lifetime user keeps lifetime when a timed grant is revoked |

There is no scheduled job; expiry is applied lazily by `get_current_user_obj`.

### What Pro unlocks

| Rule | Enforced in |
| :--- | :--- |
| More than `FREE_CV_LIMIT` (3) CVs | `POST /cvs/` — counted at creation time only |
| More than `FREE_IMPORT_LIMIT` (2) AI imports | `POST /ai/import` — lifetime total for non-Pro users |
| AI tools beyond the free allowance (below) | `require_pro` via `enforce_ai_quota`, or `reserve_rewrite` |
| More than `FREE_PUBLIC_LINK_LIMIT` (1) public link; no badge; view details | `PUT /cvs/{id}/link`, `GET /public/cv/{slug}`, `GET /cvs/{id}/link/stats` |
| Premium features: the voice mock interview (`/interviews`) | `require_premium` — Active Hunt and Lifetime only |

### Public links when Pro ends

Nothing is deleted. A non-Pro owner's **oldest** active link stays online; the others are
*paused*: they answer `404` publicly and are reported with `paused: true`, and come back by
themselves if the user upgrades again. The check is made on every public request
(`served_link_ids` in `src/services/public_links.py`), including for owners whose pass ran out
while they were away.

### What a free user gets

| Allowance | Setting | Counted |
| :--- | :--- | :--- |
| Enhance / Optimize | `FREE_AI_WEEKLY_LIMIT` (3) | per rolling 7 days |
| AI-assisted CV import | `FREE_IMPORT_LIMIT` (2) | lifetime |

Both are counted from `ai_requests` and reported in `usage` by `GET /users/me`. Only successful
calls count. Translate, ATS, cover letter and premium features are never free.

Existing CVs beyond the limit remain readable, editable and deletable after Pro lapses; only
creating new ones is blocked.

### Ways to become Pro

| Path | Grant |
| :--- | :--- |
| Stripe payment | 7 days, 30 days or lifetime, via `grant_pro` |
| `POST /promo/redeem` | The code's `granted_days`, via `grant_pro` |
| `python src/scripts/upgrade_user.py --user-id … [--days N]` | Lifetime, or `N` days, via `grant_pro` |

## Stripe

Pro is sold as one-off passes (`mode="payment"`), not subscriptions. There is nothing to renew or
cancel.

| `plan_type` | Product | Price id setting | Duration |
| :--- | :--- | :--- | :--- |
| `"7"` | Sprint Pass | `STRIPE_PRICE_7D` | 7 days |
| `"30"` | Active Hunt | `STRIPE_PRICE_30D` | 30 days |
| `"lifetime"` | Lifetime Access | `STRIPE_PRICE_LIFETIME` | no expiry |

Amounts and currency are defined on the Stripe prices, not in this code.

### Flow

```
Frontend                    Backend                                Stripe
   │  POST /billing/create-checkout-session {plan_type}
   ├──────────────────────────▶│  stripe.checkout.Session.create(
   │                           │     price, mode=payment,
   │                           │     client_reference_id=<clerk id>,
   │                           │     metadata.plan_duration=<plan_type>) ───▶│
   │◀────────── {url} ─────────┤◀──────────────────────────────── session ───┤
   │  redirect to url ────────────────────────────────────────────────────▶  │ user pays
   │                           │◀── POST /webhooks/stripe  checkout.session.completed
   │                           │    verify signature → payment_status == paid?
   │                           │    → grant_pro + payments row
   │◀── redirect to {FRONTEND_URL}/app/dashboard?session_id=… ───────────────┤
   │  GET /users/me  →  is_pro: true
```

The browser redirect and the webhook are independent; the dashboard can load before the webhook has
been processed, in which case the user briefly still appears as Free.

The Stripe SDK call is synchronous, so the route runs it with `asyncio.to_thread`.

### Webhook handling (`src/services/stripe_service.py`)

1. No `STRIPE_WEBHOOK_SECRET` → `500`. Bad payload or signature → `400`.
2. **Paid checkout** (`checkout.session.completed` or `…async_payment_succeeded`):
   - ignored unless `payment_status == "paid"` (delayed payment methods arrive later through the
     async event);
   - ignored if a `payments` row with that session id exists — **this is the idempotency key**, so
     Stripe's retries cannot grant twice;
   - otherwise `grant_pro` and insert the `payments` row (`session_id`, `user_id`, `plan`,
     `payment_intent`, `granted_days`) in one transaction.
3. **`charge.refunded`** with `refunded: true` (a full refund): find the un-refunded payment by
   `payment_intent`, `revoke_grant` for its `granted_days`, stamp `refunded_at`. Partial refunds
   leave access untouched.
4. Every other event is acknowledged and ignored.

### Stripe setup

- Create three one-off prices and put their ids in `STRIPE_PRICE_7D/30D/LIFETIME`.
- Webhook endpoint → **`{backend}/api/v1/webhooks/stripe`**, events
  `checkout.session.completed`, `checkout.session.async_payment_succeeded`, `charge.refunded`;
  its signing secret goes in `STRIPE_WEBHOOK_SECRET`.
- Local testing: `stripe listen --forward-to localhost:8000/api/v1/webhooks/stripe` prints a
  temporary `whsec_…` to use.

## Promo codes

A promo code is a row in `promo_codes`: a string (case-sensitive), a use limit and a number of Pro
days (`9999` = lifetime). Create one with the CLI:

```bash
python create_promo.py --code LAUNCH30 --uses 100 --days 30
python create_promo.py --code FOUNDER --uses 10 --days 9999     # lifetime
python create_promo.py --code OPEN --uses 0 --days 7            # unlimited uses
```

`POST /promo/redeem` (`src/api/routers/promo.py`):

1. Trim the code; lock the `promo_codes` row (`SELECT … FOR UPDATE`).
2. Reject if unknown, inactive, or `used_count` has reached `max_uses` (`max_uses = 0` = unlimited).
3. Reject if this user already has a `promo_redemptions` row for the code — **one redemption per
   user per code**, also guaranteed by a unique constraint.
4. Increment `used_count`, insert the redemption, `grant_pro(user, granted_days)`, commit.

`is_active` is a manual off switch; reaching the use limit does not flip it.

## Recruiter subscriptions

The recruiter area is a second product on the same accounts, with its own plans. It is
**independent of the job-seeker passes**: a recruiter plan does not make someone Pro, and a pass
does not open the recruiter area. State lives in `recruiter_subscriptions` (one row per user);
the rules are in `src/services/recruiter_plans.py`.

| Plan | How it starts | CVs evaluated | Candidate data kept |
| :--- | :--- | :--- | :--- |
| *(none)* — free trial | automatically | `RECRUITER_TRIAL_CVS` (10) in total, once | `RECRUITER_RETENTION_DAYS` (90) |
| `starter` | Stripe subscription, `STRIPE_PRICE_RECRUITER_STARTER` | `RECRUITER_STARTER_MONTHLY` (100) per billing month | 90 days |
| `pro` | Stripe subscription, `STRIPE_PRICE_RECRUITER_PRO` | `RECRUITER_PRO_MONTHLY` (1,000) per billing month | 90 days |
| `enterprise` | agreed by hand, `grant_recruiter` script | unlimited, or the agreed `monthly_quota` | 90 days, or the agreed `retention_days` |

### Stripe is the source of truth for Starter and Pro

`POST /recruiter/billing/checkout` opens a Checkout session in `subscription` mode. The
subscription carries `metadata.user_id`, so every later event can be matched to the user. Nothing
is granted from the checkout itself; the row is written by the webhook from:

| Event | Effect |
| :--- | :--- |
| `customer.subscription.created` / `.updated` | Plan (from the price), status and billing period are copied. Covers the first payment, renewals, upgrades, a failed payment (`past_due`) and "cancel at period end" (still `active` until the end) |
| `customer.subscription.deleted` | `canceled` |

Stripe's states map to three of ours: `active`/`trialing` → `active`; `past_due`/`unpaid` →
`past_due`; `canceled`/`incomplete_expired` → `canceled`. `incomplete` (first payment not made)
grants nothing. Events are applied idempotently and **an event older than the last one applied is
ignored** (`last_event_at`), so deliveries out of order cannot resurrect a cancelled plan. News
about a previous subscription never disturbs the current one.

Changing plan, updating the card, invoices and cancelling all happen in Stripe's customer portal
(`POST /recruiter/billing/portal`); there is no cancellation logic of our own.

### May this user evaluate another CV?

`entitlement(db, user)` answers it, and `GET /recruiter/me` returns it:

- **Running plan** (`active`, and within the paid period): usage is counted from
  `current_period_start` for Stripe plans, and over a rolling 30 days for plans agreed by hand.
- **`past_due`**: evaluating is paused until the payment is fixed; the plan is not lost.
- **Ended** (cancelled, or the paid period ran out without news from Stripe): no evaluations.
  The free trial does not come back.
- **No plan ever**: the trial.

Usage is one row per evaluated CV in `ai_requests` under the key `recruiter:evaluate`.
`reserve_evaluation` records it and `release_evaluation` gives it back when an evaluation fails.

### Stripe setup for the recruiter plans

- Two **recurring monthly** prices; their ids go in `STRIPE_PRICE_RECRUITER_STARTER` and
  `STRIPE_PRICE_RECRUITER_PRO`.
- The customer portal switched on (Settings → Billing → Customer portal), allowing plan changes
  between those two prices and cancellation.
- The existing webhook endpoint also subscribed to `customer.subscription.created`,
  `customer.subscription.updated` and `customer.subscription.deleted`.

### Enterprise

```bash
python -m src.scripts.grant_recruiter --user-id user_… [--months 12] [--quota 5000] [--retention-days 365]
python -m src.scripts.grant_recruiter --user-id user_… --revoke
```

Refuses to touch a user with a running Stripe subscription.
