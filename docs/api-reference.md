# API Reference

Base path: **`/api/v1`**. In development the interactive version of this page is at
`http://localhost:8000/docs` (disabled when `ENVIRONMENT=production`).

Unless marked otherwise, every endpoint needs `Authorization: Bearer <Clerk session token>`.

## Common responses

| Status | When | Body |
| :--- | :--- | :--- |
| `401` | Token is missing a valid signature, expired, from another issuer or origin, or has no `sub` | `{"detail": "Could not validate credentials"}` |
| `401` | No `Authorization` header at all | `{"detail": "Not authenticated"}` |
| `422` | Body or path fails validation (e.g. a CV id that is not a UUID) | FastAPI validation error list |
| `503` | Clerk's key set could not be fetched | `{"detail": "Authentication service unavailable"}` |

Errors always carry a `detail` field; the frontend's API client surfaces it as the error message.
Details are written for end users — provider and internal errors are logged, not returned.

## Summary

| Method | Path | Auth | Pro | Purpose |
| :--- | :--- | :---: | :---: | :--- |
| `GET` | `/health` *(no `/api/v1`)* | — | — | Liveness |
| `GET` | `/users/me` | ✅ | — | Current user, plan and remaining free allowances |
| `POST` | `/cvs/` | ✅ | — | Create a CV (free tier: max 3) |
| `GET` | `/cvs/` | ✅ | — | List own CVs, newest first |
| `GET` | `/cvs/{cv_id}` | ✅ | — | Read one CV |
| `PUT` | `/cvs/{cv_id}` | ✅ | — | Partial update |
| `DELETE` | `/cvs/{cv_id}` | ✅ | — | Delete |
| `POST` | `/ai/rewrite` | ✅ | free: 3 per week | Enhance / optimize / translate a CV (translate is Pro-only) |
| `POST` | `/ai/improve` | ✅ | ✅ | **Deprecated** shim for `/ai/rewrite` |
| `POST` | `/ai/cover-letter` | ✅ | ✅ | Generate a cover letter |
| `POST` | `/ai/ats` | ✅ | ✅ | ATS simulation |
| `POST` | `/billing/create-checkout-session` | ✅ | — | Start a Stripe Checkout |
| `POST` | `/promo/redeem` | ✅ | — | Redeem a promo code |
| `POST` | `/webhooks/stripe` | Stripe signature | — | Payment completed / refunded |
| `POST` | `/webhooks/clerk` | Svix signature | — | User created / updated / deleted |

## Health

### `GET /health`

```json
{ "status": "healthy", "project": "CV Studio Tools API" }
```

Does not touch the database.

## Users

### `GET /users/me`

Returns the caller's user, creating the row on first sight and applying Pro expiry.

```json
{
  "id": "user_2abc…",
  "is_pro": false,
  "pro_expires_at": null,
  "plan": "free | sprint | active | lifetime",
  "is_premium": false,
  "premium_until": null,
  "usage": {
    "free_ai":      { "limit": 3, "remaining": 2, "resets_at": null },
    "free_imports": { "limit": 2, "remaining": 2, "resets_at": null }
  }
}
```

`pro_expires_at` is `null` for free users and for lifetime Pro. `is_premium` is true for Active
Hunt (until `premium_until`) and Lifetime. `usage` is what a non-Pro user has left;
`free_ai.resets_at` is set once the weekly allowance is used up.

## CVs

Shared response shape (`CVResponse`):

```json
{
  "id": "0b6f…-uuid",
  "user_id": "user_2abc…",
  "title": "Backend Engineer",
  "content": { "personal": { "name": "…" }, "experience": [] },
  "language": "ES",
  "theme": "modern",
  "created_at": "…",
  "updated_at": "…"
}
```

`content` is any JSON object; the backend does not validate its structure. `theme` is an opaque
string chosen by the frontend (max 64 characters) or `null`.

### `POST /cvs/` → `201`

```json
{ "title": "string", "content": { }, "language": "ES", "theme": "modern" }
```

`language` (default `ES`) and `theme` are optional. Unknown fields are ignored. The server assigns
the id.

- `403` `Free tier limit reached (3 CVs). Please upgrade to Pro to create more.` — caller is not
  Pro and already owns `FREE_CV_LIMIT` CVs.

### `GET /cvs/` → `200`

Array of `CVResponse` for the caller, ordered by `updated_at` descending. No pagination.

### `GET /cvs/{cv_id}` → `200`

- `404` `CV not found`
- `403` `Not authorized to access this CV` — the CV exists but belongs to someone else.

### `PUT /cvs/{cv_id}` → `200`

```json
{ "title": "string?", "content": { }, "language": "string?", "theme": "string?" }
```

All fields optional; only those present and non-null are changed. `content` is replaced wholesale,
not merged. Same `404` / `403` as above.

### `DELETE /cvs/{cv_id}` → `204`

Same `404` / `403` as above.

## AI

All AI endpoints share the same gate (`enforce_ai_quota`), evaluated before any work is done:

| Status | Detail | Meaning |
| :--- | :--- | :--- |
| `403` | `This feature requires a Pro subscription.` | Caller is not Pro |
| `429` | `AI usage limit reached. Please try again later.` | Per-user hourly or daily limit hit; `Retry-After` header gives seconds |
| `502` | `The AI service could not process this request. Please try again.` | Provider error or unusable model output |
| `503` | `AI features are not available right now.` | `OPENAI_API_KEY` is not configured |

Size limits (→ `422`): `job_description` up to 20 000 characters; `cv_content` up to 200 000
characters of JSON.

See [ai-services.md](./ai-services.md) for what happens inside.

### `POST /ai/rewrite`

```json
{
  "cv_content": { },
  "action": "enhance" | "optimize" | "translate",
  "target_language": "es" | "en" | "pt",
  "job_description": "string (required when action is 'optimize')"
}
```
```json
{ "cv": { "…the rewritten CV, same structure…" }, "free_remaining": 2 }
```

Non-Pro users may run `enhance` and `optimize` three times per rolling week
(`"free_remaining"` counts down; it is `null` for Pro). After that, and for `translate`, the
answer is `403`.

Contact details in `cv_content` are masked before the model sees them and restored in the result.

### `POST /ai/improve` *(deprecated)*

Kept so a frontend that predates `/ai/rewrite` keeps working. Accepts
`{ "text": "<CV as JSON string>", "context": "Action: <action>, Lang: <lang>, JD: <text>" }` and
answers `{ "improved_text": "<CV as JSON string>" }`. Anything that does not match that exact
shape gets `400` `Unsupported request. Use POST /ai/rewrite.` Remove once no deployed client calls it.

### `POST /ai/cover-letter`

```json
{ "cv_content": { }, "job_description": "string", "language": "es | en | pt (optional)" }
```
```json
{ "cover_letter": "Jane Doe\nMexico City\njane@example.com\n+52…\n2026-10-06\n\nDear Hiring Manager, …" }
```

### `POST /ai/import`

Turns the text of an existing resume into a structured CV. The client extracts the text (from a
PDF, or from a JSON / YAML / TOML / XML file whose schema it does not recognise); no file is uploaded.

```json
{ "text": "string, up to 60 000 characters", "source": "pdf | structured", "language": "es | en | pt (optional)" }
```
```json
{ "cv": { "personal": { }, "experience": [ ], "education": [ ], "skills": [ ], "certifications": [ ],
          "projects": [ ], "languages": "", "interests": "", "language": "ES | EN | PT | null" },
  "remaining_free_imports": 1 }
```

Unlike the other AI routes this one is **not Pro-only**: a non-Pro user gets `FREE_IMPORT_LIMIT`
(2) imports in total, then `403` `Free import limit reached. Upgrade to Pro to import more CVs.`
Pro users share the normal AI rate limit (`429`) and get `"remaining_free_imports": null`.
`422` `No CV content could be read from this document.` when the model finds nothing. An import
that fails (`422`, `502`, `503`) does not count against the allowance.

The returned CV has no ids; items are in the shape of the frontend's `CVData`, dates are
`YYYY-MM` or `""`.

### `POST /ai/ats`

```json
{ "cv_content": { }, "job_description": "string", "language": "es | en | pt (optional)" }
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

The object is the model's JSON answer; its fields are requested by the prompt, not validated.

## Billing

### `POST /billing/create-checkout-session`

```json
{ "plan_type": "7" | "30" | "lifetime" }
```
```json
{ "url": "https://checkout.stripe.com/c/pay/…" }
```

- `422` — `plan_type` is not one of the three literals.
- `503` `This plan is not available right now.` — Stripe key or the matching `STRIPE_PRICE_*` unset.
- `502` `Could not start the checkout. Please try again.` — Stripe rejected the request.

The session is `mode="payment"` (one-off), with `client_reference_id` = the Clerk user id and
`metadata.plan_duration` = `plan_type`. Success returns the browser to
`{FRONTEND_URL}/app/dashboard?session_id=…`, cancel to `{FRONTEND_URL}/app/dashboard`.

## Promo codes

### `POST /promo/redeem`

```json
{ "code": "string" }
```
```json
{ "success": true, "message": "Promotional code redeemed successfully", "granted_days": 30 }
```

| Status | Detail |
| :--- | :--- |
| `400` | `Promo code cannot be empty` |
| `404` | `Invalid promotional code` |
| `400` | `Promotional code is no longer active` |
| `400` | `Promotional code usage limit reached` |
| `400` | `You have already redeemed this code` |
| `500` | `Could not redeem promo code` |

## Webhooks

### `POST /webhooks/stripe`

Called by Stripe. The raw body is verified against `STRIPE_WEBHOOK_SECRET` using the
`Stripe-Signature` header.

| Status | Detail |
| :--- | :--- |
| `400` | `Missing Stripe-Signature header` / `Invalid payload` / `Invalid signature` |
| `500` | `Stripe webhook secret not configured` |
| `200` | `{"status": "success"}` — for handled **and** ignored event types |

| Event | Effect |
| :--- | :--- |
| `checkout.session.completed`, `checkout.session.async_payment_succeeded` | If `payment_status` is `paid`: grant the plan to `client_reference_id` and record the payment. A session is applied once, however often it is delivered |
| `charge.refunded` (full refund) | Take back the grant recorded for that payment intent |
| anything else | Ignored |

### `POST /webhooks/clerk`

Called by Clerk (delivered through Svix). The raw body is verified against `CLERK_WEBHOOK_SECRET`
using the `svix-id`, `svix-timestamp` and `svix-signature` headers.

| Status | Detail |
| :--- | :--- |
| `400` | `Invalid signature` / `Invalid payload` |
| `500` | `Clerk webhook secret not configured` |
| `200` | `{"status": "success"}` |

| Event | Effect |
| :--- | :--- |
| `user.created`, `user.updated` | Create the user row if needed and store the primary email |
| `user.deleted` | Delete the user and, by cascade, their CVs, promo redemptions and AI usage |
| anything else | Ignored |
