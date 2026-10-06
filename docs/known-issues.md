# Known Issues and Gotchas

Found while reading the code to write this knowledge base (commit `e0f98e4`). Nothing here has been
fixed. Confidence labels:

- **Read** — follows directly from the code.
- **Ran** — reproduced by executing something.
- **Likely** — follows from the code but depends on runtime behaviour that was not exercised. The
  service was not started and the test suite was not run while writing this (the local Python had
  no `asyncpg`).

Delete entries as they are resolved.

## Security — fix before production traffic

### 1. JWT signatures are not verified — Read
`src/core/security.py:17` decodes the bearer token with `options={"verify_signature": False}`.
Signature, expiry, issuer and audience are all unchecked. Anyone who can reach the API can forge a
token with any `sub` and then read, modify or delete that user's CVs, redeem codes for them, or use
a Pro user's AI quota. The code comment acknowledges it is a placeholder.

Fix: fetch Clerk's JWKS (`https://<clerk-frontend-api>/.well-known/jwks.json`, cached), and
`jwt.decode(token, key, algorithms=["RS256"], …)` with expiry and issuer checks. `PyJWT` needs the
`cryptography` package for RS256. `CLERK_API_KEY` is currently unused and is not what is needed
for this.

### 2. The Clerk webhook is unauthenticated — Read
`POST /api/v1/webhooks/clerk` (`routers/webhooks.py:28`) trusts any JSON body. A single request
`{"type":"user.deleted","data":{"id":"<clerk user id>"}}` permanently deletes that user's CVs and
their user row (including Pro status). Clerk signs webhooks with Svix; the handler should verify
the `svix-id`, `svix-timestamp` and `svix-signature` headers against the endpoint's signing secret.

### 3. CV content is sent unmasked to OpenAI by `/ai/improve` — Read
`mask_cv_pii` is applied in the ATS and cover-letter services but not in `improve_text`, which
receives the CV as an opaque string. Enhance, optimize and translate therefore send email, phone,
city and social URLs to the provider. The frontend's privacy page advertises automatic
anonymisation. The candidate's name is not masked by any feature.

### 4. Job descriptions are injected into the system prompt — Read
`improvement.py:42` interpolates the user-supplied job description into the system message, and the
whole `context` string is repeated in the user message. Combined with item 7, user text controls
both the instructions and the mode selection.

### 5. Internal errors are returned to clients — Read
The AI handlers and `create-checkout-session` respond with `detail=str(e)`. Provider and Stripe
error messages reach the browser verbatim.

### 6. No rate limiting — Read
Nothing bounds the number or size of AI requests per user; a Pro account (or, given item 1, anyone)
can generate unbounded OpenAI cost.

## Bugs

### 7. Mode detection reads the job description — Read
`improve_text` looks for `translate` / `optimize` anywhere in the lower-cased `context`, which
includes the pasted job description, and checks translation first (`improvement.py:14-15, 32`). An
**optimize** request whose job description contains the word "translate" is handled as a
translation. Likewise `lang: en` etc. are matched anywhere in the string. Fix: accept `action`,
`lang` and `job_description` as separate request fields.

### 8. Non-Pro callers get `500`, not `403` — Ran
`check_pro_status` raises `HTTPException(403)` inside each AI handler's `try`, and the
`except Exception` re-raises it as `500` with detail `"403: This feature requires a Pro
subscription."` (confirmed: `str(HTTPException(403, "x"))` is `"403: x"`). Clients cannot
distinguish "not Pro" from a server failure. Fix: check Pro before the `try`, or
`except HTTPException: raise` first.

### 9. `/users/me` does not apply Pro expiry — Read
It depends on `get_current_user_id` (`routers/users.py:12`), bypassing the expiry check in
`get_current_user`. After a pass runs out, `/users/me` keeps answering `is_pro: true` until the
user happens to call another authenticated endpoint. The frontend uses `/users/me` to decide what
to show, so an expired user can still see Pro UI; the AI endpoints themselves do enforce expiry.

### 10. A Stripe purchase overwrites remaining Pro time — Read
`stripe_service.py:46` sets `pro_expires_at` from "now", ignoring any current value. Buying 7 days
with 20 days left shortens access; buying a timed pass as a lifetime user ends lifetime. The
frontend disables purchase buttons for Pro users, but that is the only guard. `/billing/redeem` has
the same behaviour; `/promo/redeem` extends correctly.

### 11. Promo codes can be redeemed repeatedly by the same user — Read
There is no redemption record, only a counter. A code with `max_uses > 1` can be redeemed by one
account until the counter runs out, stacking days each time.

### 12. Stripe webhook does not check payment state or duplicates — Read
`checkout.session.completed` is acted on without looking at `payment_status`, and events are not
de-duplicated. Refunds and disputes are ignored, so a refunded user stays Pro.

### 13. `upgrade_user.py --email` cannot work — Read
`users.email` is never written by the application, so the lookup finds nothing; the script then
tries to insert a user with `id=None`. Use `--user-id`. The script also leaves `pro_expires_at`
unchanged.

### 14. CV list has no ordering — Read
`GET /cvs/` returns rows in database order, so the dashboard order is not guaranteed to be
"most recently updated first".

## Schema and migrations

### 15. Alembic history is not usable — Read
The first revision is empty and there is no baseline; the schema is really produced by
`create_all` at startup. `alembic upgrade head` fails on both an empty database and a freshly
app-created one. Details and a workaround in
[development.md](./development.md#database-and-migrations). Fix: generate a baseline revision
that creates all three tables, and stop calling `create_all` in production.

### 16. `create_all` hides missing migrations — Read
A new **column** on an existing table works on a fresh local database and fails in production with
`column does not exist`, because `create_all` never alters tables.

### 17. No `theme` anywhere in the CV model — Read
The frontend's API types expect a `theme` on listed CVs, but there is no column and no schema
field. The value is always absent, so the frontend's dashboard always falls back to its first theme.

### 18. Deleting a user depends on manual ordering — Read
`cvs.user_id` has no `ON DELETE CASCADE`; the Clerk webhook deletes CVs first by hand. Any other
code path deleting a user will hit the foreign key.

## Operations

### 19. Production image runs with `--reload` on a fixed port — Read / Likely impact
`Dockerfile` `CMD` is the development command. Unless the platform start command overrides it,
production runs a file watcher and listens only on 8000.

### 20. SQL echo and debug prints are always on — Read
`create_async_engine(..., echo=True)` logs every statement — including CV JSON bound as parameters
— and the AI path prints the full `context` (the job description) on every call. Logs therefore
contain user content.

### 21. Deployment checklist is out of date — Read
`PROD-ENV-CHECKLIST.md` in the frontend repo gives the Stripe webhook path as
`/api/v1/billing/webhooks` (actual: `/api/v1/webhooks/stripe`) and the health check as
`/api/v1/health` (actual: `/health`). A webhook registered at the documented path would 404 and no
payment would ever grant Pro.

### 22. Synchronous Stripe call in an async handler — Read
`stripe.checkout.Session.create` blocks the event loop for the duration of the HTTP call.

## Stale or unused

| Item | Status |
| :--- | :--- |
| `CLERK_API_KEY` setting | Never read |
| DeepSeek client and settings | Built, never selected; the frontend still says "Powered by Deepseek" |
| `src/services/ai/translation.py` | Not imported |
| `POST /billing/redeem` | Superseded by `/promo/redeem`; not called by the frontend |
| `psycopg2-binary`, `python-multipart` | Installed, not used |
| `testDB.py`, `test_get_cv.py` | Debug scripts in the repo root, one with a hardcoded CV id |
| Root `__init__.py` | Empty; makes the repo root look like a package |
| `README.md` licence section | Placeholder text |
| Second `get_db` in `src/db/database.py` | Duplicate of the one in `api/dependencies.py` |

## Mismatches with the frontend

| Frontend assumes | Backend does |
| :--- | :--- |
| It chooses the CV id (`createCV` sends `id`) | Ignores it and generates a UUID; the response id is authoritative (the frontend does use it) |
| `getCVs` items include `theme` | No such field |
| `content` might arrive as a JSON string | Always a JSON object |
| Stale CV id on save → `404` → create a new CV | `404` only if the row is gone; another user's CV gives `403`, a malformed id `422` — neither triggers the fallback |
| A fourth CV can be created from the editor or via "AI: create a copy" | `403`; the frontend shows a generic save error |
| `generateCoverLetter` result is used as a string | Returns `{ "cover_letter": "…" }` — the frontend passes the object to its modal |
| Promo redemption UI | Exists only on the frontend's `main` branch, not on `master` |
