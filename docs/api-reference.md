# API Reference

Base path: **`/api/v1`**. In development the interactive version of this page is at
`http://localhost:8000/docs` (disabled when `ENVIRONMENT=production`).

Unless marked otherwise, every endpoint needs `Authorization: Bearer <Clerk session token>`.

## Common responses

| Status | When | Body |
| :--- | :--- | :--- |
| `401` | Token cannot be decoded or has no `sub` | `{"detail": "Could not validate credentials"}` |
| `403` | No `Authorization` header at all (FastAPI's `HTTPBearer` default) | `{"detail": "Not authenticated"}` |
| `422` | Body or path fails validation (e.g. a CV id that is not a UUID) | FastAPI validation error list |

Errors always carry a `detail` field; the frontend's API client surfaces it as the error message.

## Summary

| Method | Path | Auth | Pro | Purpose |
| :--- | :--- | :---: | :---: | :--- |
| `GET` | `/health` *(no `/api/v1`)* | — | — | Liveness |
| `GET` | `/users/me` | ✅ | — | Current user and Pro status |
| `POST` | `/cvs/` | ✅ | — | Create a CV (free tier: max 3) |
| `GET` | `/cvs/` | ✅ | — | List own CVs |
| `GET` | `/cvs/{cv_id}` | ✅ | — | Read one CV |
| `PUT` | `/cvs/{cv_id}` | ✅ | — | Partial update |
| `DELETE` | `/cvs/{cv_id}` | ✅ | — | Delete |
| `POST` | `/ai/improve` | ✅ | ✅ | Enhance / optimize / translate |
| `POST` | `/ai/cover-letter` | ✅ | ✅ | Generate a cover letter |
| `POST` | `/ai/ats` | ✅ | ✅ | ATS simulation |
| `POST` | `/billing/create-checkout-session` | ✅ | — | Start a Stripe Checkout |
| `POST` | `/billing/redeem` | ✅ | — | Redeem a promo code (older implementation) |
| `POST` | `/promo/redeem` | ✅ | — | Redeem a promo code (current implementation) |
| `POST` | `/webhooks/stripe` | Stripe signature | — | Payment completed |
| `POST` | `/webhooks/clerk` | **none** | — | User deleted |

## Health

### `GET /health`

```json
{ "status": "healthy", "project": "CV Studio Tools API" }
```

Does not touch the database.

## Users

### `GET /users/me`

Returns the caller's `users` row, creating it if this is their first request. There is no response
model, so the whole row is serialised:

```json
{
  "id": "user_2abc…",
  "email": null,
  "is_pro": false,
  "pro_expires_at": null,
  "created_at": "2026-06-19T10:00:00Z",
  "updated_at": null
}
```

This endpoint depends on `get_current_user_id`, not `get_current_user`, so it does **not** apply
Pro expiry. See [known-issues.md](./known-issues.md).

## CVs

Shared response shape (`CVResponse`):

```json
{
  "id": "0b6f…-uuid",
  "user_id": "user_2abc…",
  "title": "Backend Engineer",
  "content": { "personal": { "name": "…" }, "experience": [] },
  "language": "ES",
  "created_at": "…",
  "updated_at": "…"
}
```

`content` is any JSON object. The backend does not validate its structure.

### `POST /cvs/` → `201`

```json
{ "title": "string", "content": { }, "language": "ES" }
```

`language` is optional (default `ES`). Extra fields are ignored — the frontend sends an `id`, which
is discarded; the server assigns its own UUID and the client must use the one in the response.

- `403` `Free tier limit reached (3 CVs). Please upgrade to Pro to create more.` — caller is not
  Pro and already owns three or more CVs.

### `GET /cvs/` → `200`

Array of `CVResponse` for the caller. No pagination and no explicit ordering.

### `GET /cvs/{cv_id}` → `200`

- `404` `CV not found`
- `403` `Not authorized to access this CV` — the CV exists but belongs to someone else.

### `PUT /cvs/{cv_id}` → `200`

```json
{ "title": "string?", "content": { }, "language": "string?" }
```

All fields optional; only those present and non-null are changed. `content` is replaced wholesale,
not merged. Same `404` / `403` as above.

### `DELETE /cvs/{cv_id}` → `204`

Same `404` / `403` as above.

## AI

All three require `is_pro`. See [ai-services.md](./ai-services.md) for what happens inside.

Every handler wraps its whole body in `try / except Exception`, so **all failures come back as
`500` with the exception text in `detail`** — including the "not Pro" check, which surfaces as
`500` `"403: This feature requires a Pro subscription."`.

### `POST /ai/improve`

```json
{ "text": "string", "context": "string (optional, default 'resume bullet point')" }
```
```json
{ "improved_text": "string" }
```

When `text` starts with `{`, the model is forced into JSON mode and `improved_text` is a JSON
**string** the caller must parse. `context` is a free-text control channel; the frontend sends
`"Action: <enhance|optimize|translate>, Lang: <es|en|pt>, JD: <job description>"`.

### `POST /ai/cover-letter`

```json
{ "cv_content": { }, "job_description": "string" }
```
```json
{ "cover_letter": "Jane Doe\nMexico City\njane@example.com\n+52…\nJune 19, 2026\n\nDear Hiring Manager, …" }
```

### `POST /ai/ats`

```json
{ "cv_content": { }, "job_description": "string" }
```
```json
{
  "final_ats_score": 78,
  "overall_interview_probability": 55,
  "tier_classification": "Top Match | Competitive | Needs Improvement | Weak Match",
  "hard_requirements_analysis": [
    { "requirement": "5+ years Python", "status": "match | missing | partial", "comment": "…" }
  ],
  "missing_keywords": ["Kubernetes"],
  "top_improvement_actions": ["…"]
}
```

The object is whatever the model returned, parsed with `json.loads`; it is not validated against
this shape.

## Billing

### `POST /billing/create-checkout-session`

```json
{ "plan_type": "7" | "30" | "lifetime" }
```
```json
{ "url": "https://checkout.stripe.com/c/pay/…" }
```

- `422` — `plan_type` is not one of the three literals.
- `400` `Invalid plan type or Price ID not configured` — the matching `STRIPE_PRICE_*` is unset.
- `500` — any Stripe error, with Stripe's message in `detail`.

The session is `mode="payment"` (one-off), with `client_reference_id` = the Clerk user id and
`metadata.plan_duration` = `plan_type`. Success returns the browser to
`{FRONTEND_URL}/app/dashboard?session_id=…`, cancel to `{FRONTEND_URL}/app/dashboard`.

### `POST /billing/redeem` and `POST /promo/redeem`

Both take `{ "code": "string" }`. They are two implementations of the same feature with different
rules — compared in [auth-plans-billing.md](./auth-plans-billing.md#promo-codes). The frontend
(on its `main` branch) calls **`/promo/redeem`**.

`/promo/redeem` →

```json
{ "success": true, "message": "Promotional code redeemed successfully", "granted_days": 30 }
```

| Status | Detail |
| :--- | :--- |
| `400` | `Promo code cannot be empty` |
| `404` | `Invalid promotional code` |
| `400` | `Promotional code is no longer active` |
| `400` | `Promotional code usage limit reached` |
| `404` | `User not found` |
| `500` | `Could not redeem promo code` |

`/billing/redeem` →

```json
{ "success": true, "message": "Code redeemed successfully! 30 days of Pro access granted.", "is_pro": true }
```

- `400` `Invalid or expired code` for every failure case.

## Webhooks

### `POST /webhooks/stripe`

Called by Stripe. Requires the `Stripe-Signature` header; the raw body is verified against
`STRIPE_WEBHOOK_SECRET`.

| Status | Detail |
| :--- | :--- |
| `400` | `Missing Stripe-Signature header` / `Invalid payload` / `Invalid signature` |
| `500` | `Stripe webhook secret not configured` |
| `200` | `{"status": "success"}` — for handled **and** unhandled event types |

Only `checkout.session.completed` has an effect: the user named by `client_reference_id` becomes
Pro, with expiry now + 7 or 30 days, or no expiry for `lifetime`.

### `POST /webhooks/clerk`

Called by Clerk. Reads the JSON body; on `type == "user.deleted"` deletes that user's CVs and then
the user row. Always returns `{"status": "success"}`. **The request is not authenticated** — see
[known-issues.md](./known-issues.md) item 2.
