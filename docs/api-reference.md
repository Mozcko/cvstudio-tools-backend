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
| `POST` | `/interviews` | ✅ | premium | Start a mock interview |
| `GET` | `/interviews` | ✅ | premium | Own interviews, newest first |
| `GET` / `DELETE` | `/interviews/{id}` | ✅ | premium | One interview with its transcript and report / delete it |
| `POST` | `/interviews/{id}/answer` | ✅ | premium | Answer the current question (audio or text) |
| `GET` | `/interviews/{id}/turns/{n}/audio` | ✅ | premium | Speech for something the recruiter said |
| `POST` | `/interviews/{id}/finish` | ✅ | premium | End the interview and get the report |
| `GET` | `/links` | ✅ | — | Own public links with view counts |
| `GET` | `/links/check` | ✅ | — | Is a link name available? |
| `POST` | `/links/seen` | ✅ | — | Mark current views as seen |
| `PUT` / `DELETE` | `/cvs/{cv_id}/link` | ✅ | free: 1 active link | Publish a CV, change or remove its link |
| `GET` | `/cvs/{cv_id}/link/stats` | ✅ | details: Pro | View statistics of a link |
| `GET` | `/public/cv/{slug}` | **none** | — | The published CV, as anyone may read it |
| `POST` | `/public/cv/{slug}/view` | **none** | — | Count one visit |
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
    "free_imports": { "limit": 2, "remaining": 2, "resets_at": null },
    "interviews_daily":   { "limit": 3,  "remaining": 3,  "resets_at": null },
    "interviews_monthly": { "limit": 30, "remaining": 30, "resets_at": null }
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

## Mock interview

Premium only (Active Hunt and Lifetime): everyone else gets `403`
`This feature requires the Active Hunt or Lifetime plan.` on every route. Someone else's
interview is `404`. See [ai-services.md](./ai-services.md#mock-interview) for how it works.

### `POST /interviews` → `201`

```json
{ "cv_content": { }, "job_description": "20 to 20 000 characters", "language": "es | en | pt",
  "question_count": 6 }
```

`question_count` is 4 to 8 (default 6). Returns the session (shape below) with the recruiter's
first line. `429` with `Retry-After` when the user has started `INTERVIEW_DAILY_LIMIT` (3)
interviews in the last 24 hours or `INTERVIEW_MONTHLY_LIMIT` (30) in the last 30 days. An
interview only counts once its questions were generated.

```json
{
  "id": "uuid", "title": "Senior Python Engineer", "language": "es",
  "status": "active | completed", "question_count": 6, "current_question": 0, "done": false,
  "overall_score": null, "created_at": "…", "completed_at": null,
  "questions": ["…the questions asked so far, as prepared…"],
  "turns": [
    { "index": 0, "role": "recruiter | candidate", "kind": "question | follow_up | answer | closing",
      "question": 0, "text": "Hola Jane, gracias por tu tiempo… ¿…?", "at": "…" }
  ],
  "report": null
}
```

`done` becomes true when the recruiter has said goodbye; `current_question` then equals
`question_count`. `questions` only lists what has been asked: later ones are not revealed early.

### `POST /interviews/{id}/answer`

The answer to the current question, in one of two forms:

- **Recording:** the request body is the audio itself, with `Content-Type` `audio/webm`,
  `audio/ogg`, `audio/mp4`, `audio/x-m4a`, `audio/mpeg` or `audio/wav` (parameters such as
  `;codecs=opus` are fine). Up to 5 MB.
- **Typed:** `Content-Type: application/json`, `{ "text": "…" }`, up to 4 000 characters.

```json
{ "answer": { "…the candidate turn; text is the transcript…" },
  "reply":  { "…the recruiter turn: a follow-up, the next question or the closing…" },
  "current_question": 1, "done": false }
```

| Status | When |
| :--- | :--- |
| `409` | The interview is over, expired (2 hours after it started), or this question was answered by another request |
| `413` / `415` | Recording too large / body is neither audio nor JSON |
| `422` | Empty recording, nothing audible in it, or empty text |
| `502` / `503` | Provider failure / not configured. Nothing is recorded; the same answer can be sent again |

### `GET /interviews/{id}/turns/{n}/audio`

`audio/mpeg` for recruiter turn `n`. `404` for a turn that does not exist or was said by the
candidate. Each interview may generate speech at most twice per recruiter turn (`429` after).

### `POST /interviews/{id}/finish`

Ends the interview at any point and returns the session with `status: "completed"` and:

```json
"report": {
  "overall_score": 72, "summary": "…",
  "strengths": ["…"], "improvements": ["…"], "tips": ["…"],
  "answers": [ { "question": 0, "score": 7, "went_well": "…", "improve": "…", "sample_answer": "…" } ]
}
```

`400` when no question was answered. Calling it again returns the stored report.

## Public links

A CV can be published at `/u/<name>` on the site. One link per CV. See
[auth-plans-billing.md](./auth-plans-billing.md) for the plan rules.

### `PUT /cvs/{cv_id}/link`

Creates the link or changes it.

```json
{ "slug": "juan-perez", "is_active": true, "show_email": true, "show_phone": false, "indexable": false }
```
```json
{ "cv_id": "uuid", "slug": "juan-perez", "is_active": true, "paused": false,
  "show_email": true, "show_phone": false, "indexable": false,
  "views_total": 0, "views_new": 0, "created_at": "…" }
```

The name is lower-cased; 3–40 characters of `a-z`, `0-9` and single hyphens, not starting or
ending with a hyphen, and not a reserved word (`admin`, `api`, `app`, `pricing`, …).

| Status | When |
| :--- | :--- |
| `403` | A non-Pro user already has `FREE_PUBLIC_LINK_LIMIT` (1) active link on another CV |
| `404` | The CV does not exist or belongs to someone else |
| `409` | The name is taken |
| `422` | The name is invalid or reserved |

`paused` is true for a link that is switched on but not online, because the owner's plan allows
fewer links than they have active (see the plan rules).

`DELETE /cvs/{cv_id}/link` removes the link and its statistics and frees the name.

### `GET /links`, `GET /links/check`, `POST /links/seen`

`GET /links` returns the caller's links in the shape above. `views_new` counts views since the
last `POST /links/seen`.

`GET /links/check?slug=…&cv_id=…` → `{ "slug": "juan-perez", "available": false, "reason":
"length | format | reserved | taken" }`. With `cv_id`, the name that CV already holds counts as
available.

### `GET /cvs/{cv_id}/link/stats`

```json
{ "views_total": 42, "visitors_total": 30,
  "daily": [ { "day": "2026-10-07", "views": 3 } ],
  "referrers": [ { "host": "linkedin.com", "views": 12 }, { "host": null, "views": 9 } ] }
```

`daily` (the last 30 days, every day present) and `referrers` (top 5; `null` host = unknown
origin) are `null` for non-Pro users.

### `GET /public/cv/{slug}` — no authentication

```json
{ "slug": "juan-perez", "title": "…", "language": "ES", "theme": "modern",
  "content": { "…the CV…" }, "badge": true, "indexable": false, "updated_at": "…" }
```

`content` is the CV with `personal.email` / `personal.phone` blanked unless the owner chose to
show them (in a Markdown-mode CV the matching text is removed). `badge` is true when the owner is
not Pro. Nothing in the response identifies the account. `404`, always the same, when the link
does not exist, is switched off, or is paused. Cached for 60 seconds.

### `POST /public/cv/{slug}/view` — no authentication

Body `{ "referrer": "https://…" }` (optional). `204`. See *View statistics* in
[architecture.md](./architecture.md) for what is and is not stored.

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
