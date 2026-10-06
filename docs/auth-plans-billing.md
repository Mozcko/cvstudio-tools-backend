# Authentication, Plans and Billing

## Authentication

The frontend signs users in with Clerk and sends the Clerk session JWT as a Bearer token. Two
dependencies turn that into a user:

| Dependency | File | Does |
| :--- | :--- | :--- |
| `get_current_user_id` | `src/core/security.py` | Decode the JWT, return the `sub` claim |
| `get_current_user` | `src/api/dependencies.py` | The above, then ensure a `users` row exists and apply Pro expiry |

Use **`get_current_user`** in new routes. `get_current_user_id` skips both the row creation and the
expiry check; today only `/users/me` uses it directly (and creates the row itself).

Both return the user id as a **string**. A handler that needs `is_pro` must query `User` again, as
`cv.py`, `ai.py` and the promo routes do.

### User records

There is no sign-up endpoint. A `users` row appears the first time a Clerk user id is seen, by
whichever of these runs first:

- any authenticated request (`get_current_user`), or `/users/me`;
- a Stripe `checkout.session.completed` webhook for an unknown user;
- `POST /billing/redeem` for an unknown user;
- `scripts/upgrade_user.py`.

Only the id is stored. `email` is never filled in — there is no Clerk `user.created` /
`user.updated` handling.

### Account deletion

`POST /webhooks/clerk` handles `user.deleted` by deleting the user's CVs and then the user row —
the "right to erasure" path referenced by the frontend's privacy policy. Promo-code usage counts
are not adjusted.

## The Pro lifecycle

State lives in two columns:

| `is_pro` | `pro_expires_at` | Meaning |
| :--- | :--- | :--- |
| `false` | `null` | Free |
| `true` | a future timestamp | Pro until then (7-day or 30-day pass, or a promo) |
| `true` | `null` | Lifetime |
| `true` | a past timestamp | Expired but not yet noticed — becomes Free on the user's next authenticated request |

There is no scheduled job. `get_current_user` compares `pro_expires_at` with the current UTC time
on each request and, if it has passed, sets `is_pro = false` and clears the timestamp.

### What Pro unlocks

| Rule | Enforced in |
| :--- | :--- |
| More than 3 CVs | `POST /cvs/` (`routers/cv.py`) — counted at creation time only |
| AI endpoints | `check_pro_status` in `routers/ai.py` |

Existing CVs beyond three remain readable, editable and deletable after Pro lapses; only creating
new ones is blocked.

### Ways to become Pro

| Path | Sets expiry to |
| :--- | :--- |
| Stripe payment (`/webhooks/stripe`) | now + 7d / now + 30d / none (lifetime) — **overwrites** |
| `POST /promo/redeem` | **extends** the current expiry if still Pro, else now + N days; none if N ≥ 9999 |
| `POST /billing/redeem` | now + N days, none if N ≥ 9999 — **overwrites** |
| `python src/scripts/upgrade_user.py --user-id …` | leaves `pro_expires_at` untouched |

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
   │                           │    verify signature → users.is_pro = true, set expiry
   │◀── redirect to {FRONTEND_URL}/app/dashboard?session_id=… ───────────────┤
   │  GET /users/me  →  is_pro: true
```

The browser redirect and the webhook are independent; the dashboard can load before the webhook has
been processed, in which case the user briefly still appears as Free.

### Webhook handling (`src/services/stripe_service.py`)

1. No `STRIPE_WEBHOOK_SECRET` → `500`.
2. `stripe.Webhook.construct_event` verifies the signature against the raw body.
3. For `checkout.session.completed`: read the user id from `client_reference_id` (fallback
   `metadata.user_id`) and the plan from `metadata.plan_duration`; set `is_pro = true` and the
   expiry; create the user row if it does not exist.
4. Every other event type is acknowledged and ignored.

Not handled: `payment_status` on the session, refunds, disputes, duplicate deliveries.

### Stripe setup

- Create three one-off prices and put their ids in `STRIPE_PRICE_7D/30D/LIFETIME`.
- Add a webhook endpoint pointing to **`{backend}/api/v1/webhooks/stripe`** for
  `checkout.session.completed`, and put its signing secret in `STRIPE_WEBHOOK_SECRET`.
- Local testing: `stripe listen --forward-to localhost:8000/api/v1/webhooks/stripe` prints a
  temporary `whsec_…` to use.

## Promo codes

A promo code is a row in `promo_codes`: a string, a use limit and a number of Pro days (`9999` =
lifetime). Create one with the CLI:

```bash
python create_promo.py --code LAUNCH30 --uses 100 --days 30
python create_promo.py --code FOUNDER --uses 10 --days 9999     # lifetime
```

There are **two redeem endpoints** with different behaviour:

| | `POST /promo/redeem` (`routers/promo.py`) | `POST /billing/redeem` (`routers/billing.py`) |
| :--- | :--- | :--- |
| Used by the frontend | Yes (frontend `main` branch) | No |
| Row locking | `SELECT … FOR UPDATE` on code and user | None |
| Input | Trimmed; empty rejected | Used as is |
| `max_uses = 0` | Unlimited | Always rejected |
| Reaching the limit | Stays active; rejected by count | Sets `is_active = false` |
| Existing Pro time | Extended | Overwritten |
| Unknown user | `404` | Creates the user |
| Errors | Distinct status and message per case | Single `400` |

Neither records which user redeemed which code, so one user can redeem a multi-use code more than
once.
