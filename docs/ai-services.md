# AI Services

Code: `src/services/ai/`, exposed by `src/api/routers/ai.py`.

## Provider and model

`src/services/ai/base.py` exposes `get_ai_client()` → `(AsyncOpenAI client, model name)`. The client
is created lazily from `OPENAI_API_KEY`; the model comes from the `OPENAI_MODEL` setting (default
`gpt-4o-mini`). Without a key it raises `AINotConfiguredError`, which the router turns into `503`.

There is one provider. To use another OpenAI-compatible service, this function is the only place
to change.

No temperature, token limit, timeout or retry is set on the calls — SDK defaults apply.

## The gate: Pro and rate limit

ATS, cover letter and the deprecated `/ai/improve` depend on `enforce_ai_quota`
(`src/api/dependencies.py`):

1. `require_pro` → `403` for non-Pro users.
2. Count the user's rows in `ai_requests` for the last hour and the last day. At or above
   `AI_RATE_LIMIT_PER_HOUR` (20) / `AI_RATE_LIMIT_PER_DAY` (100) → `429` with a `Retry-After`
   header (seconds until the oldest call leaves the window). A limit of `0` disables that window.
3. Otherwise insert an `ai_requests` row (`user_id`, `endpoint`) and continue.

The call is recorded before the provider is contacted, so failed attempts count too. The table
doubles as a simple usage log:

```sql
SELECT user_id, endpoint, count(*) FROM ai_requests
WHERE created_at > now() - interval '7 days' GROUP BY 1, 2 ORDER BY 3 DESC;
```

Request bodies are size-limited in `src/schemas/ai_schemas.py` (job description 20 000 characters,
CV 200 000 characters of JSON).

### Rewrite: a weekly allowance for free users

`POST /ai/rewrite` uses `reserve_rewrite` instead. Pro users get every action under the rate
limit above. A non-Pro user may run **enhance** and **optimize** `FREE_AI_WEEKLY_LIMIT` (3) times
per rolling 7 days (`translate` answers `403`). Free uses are recorded in `ai_requests` under the
key `free:rewrite`, so what someone did while Pro never counts against their free allowance.
The response carries `free_remaining`.

Like the import, the allowance is reserved in the handler after the body is valid and released
if the AI call fails (`release_allowance`).

### The exception: CV import

`POST /ai/import` is open to every signed-in user. `reserve_import` (`src/api/dependencies.py`)
applies the rate limit above to Pro users and gives everyone else `FREE_IMPORT_LIMIT` (2) imports
in total, counted as their `ai_requests` rows for that endpoint. It is called from the handler,
not as a dependency, so a request with an invalid body is rejected before anything is recorded;
and the handler deletes the row again when the import fails, so only successful imports count.

## PII masking (`src/utils/sanitizer.py`)

**Every** CV is masked before it is sent to the model.

`mask_cv_pii(cv)` deep-copies the CV and replaces these with `"[REDACTED_PII]"`:

- `personal.email`, `personal.phone`, `personal.city`, `personal.address`
- every `personal.socials[].url`

`restore_cv_pii(original, processed)` is the inverse, used when the model returns a CV: it puts the
real values back **from the original**, so whatever the model wrote in those fields is discarded.
If the model changed the number of social links, the user's own list is restored whole.

Not masked: the candidate's name, the summary, and everything in experience, education, projects
and custom sections.

| Feature | Masked | Restored |
| :--- | :---: | :---: |
| Rewrite (enhance / optimize / translate) | ✅ | ✅ |
| ATS simulation | ✅ | n/a (no CV in the answer) |
| Cover letter | ✅ | n/a (header is built in Python from the real values) |
| Import | ✅ (text) | ✅ |

An imported document is free text, not a CV object, so it has its own pair:
`mask_text_pii(text)` replaces e-mail addresses, links and phone numbers with placeholders
(`[[EMAIL_1]]`, `[[LINK_1]]`, `[[PHONE_1]]`) and returns the mapping; `restore_text_pii` puts the
values back in every string of the result. Date ranges are recognised and left alone. A postal
address or city in the text is **not** masked — there is no reliable pattern for it.

The model's answer is validated against `ImportedCV` (`src/schemas/ai_schemas.py`): unknown keys
are dropped, wrong types become empty values, and strings and lists are capped.

## Prompt structure

All three services follow the same rules:

- The **system** message holds only our instructions. User-supplied text never goes there.
- The **user** message carries the data in tags: `<cv>…</cv>` and
  `<job_description>…</job_description>`.
- The system message states that tag contents are data, not instructions.
- `target_language` / `language` is one of `es`, `en`, `pt`, mapped to a language name in
  `LANGUAGE_NAMES`.

## The three features

### Rewrite — `rewrite_cv(cv_content, action, target_language, job_description)`

`rewrite.py`, behind `POST /ai/rewrite`. `action` is a validated enum, so the mode can only be what
the client asked for:

| `action` | System prompt intent |
| :--- | :--- |
| `enhance` | More professional, impactful, metric-driven wording with strong action verbs; keep the meaning and the number of items |
| `optimize` | Weave the job description's keywords into summary, experience and skills; preserve content; never invent experience. Requires `job_description` |
| `translate` | 1:1 translation into the target language; keep the exact number of items; do not translate proper names |

All modes add the same JSON rules: return only a JSON object with the same structure and keys,
keep ids, dates and URLs, and leave `[REDACTED_PII]` values untouched. The call uses
`response_format={"type": "json_object"}`.

Flow: mask → call → `json.loads` → must be an object (else `AIResponseError` → `502`) →
`restore_cv_pii` → `{ "cv": … }`.

The frontend merges the result over the user's data defensively (see the frontend's
`docs/auth-billing-ai.md`), so a model that drops a section cannot erase it.

`POST /ai/improve` is a deprecated shim: it parses the old `"Action: …, Lang: …, JD: …"` context
string with a strict regular expression and calls the same `rewrite_cv`.

### ATS simulation — `simulate_ats(cv_data, job_description, language)`

`ats.py`. Masks the CV and asks, in JSON mode, for a fixed structure (score, interview probability,
tier, per-requirement analysis, missing keywords, improvement actions). With `language`, free-text
values are requested in that language while `status` values stay `match | missing | partial`
(the frontend switches on them). The parsed object is returned as is.

### Cover letter — `generate_cover_letter(cv_data, job_description, language)`

`cover_letter.py`:

1. Read `name`, `email`, `phone`, `city` from the **unmasked** CV.
2. Mask the CV and ask the model for the letter **body only**, starting at the salutation
   (in `language` if given).
3. Build the header in Python — name, city, email, phone (those that exist) and today's date as
   `YYYY-MM-DD` — and prepend it.

## Error handling

`ai_errors()` in `routers/ai.py` wraps each call:

| Raised inside | Response | Logged |
| :--- | :--- | :--- |
| `HTTPException` | passed through unchanged | — |
| `AINotConfiguredError` | `503`, generic detail | error |
| anything else (provider error, bad JSON, …) | `502`, generic detail | full traceback |

Provider messages never reach the client. Look in the server log for the cause.

## Changing things

| Task | Where |
| :--- | :--- |
| Switch model | `OPENAI_MODEL` setting |
| Switch provider | `get_ai_client` in `base.py` |
| Edit a prompt | `build_system_prompt` in `rewrite.py`, or the `system_prompt` in `ats.py` / `cover_letter.py` |
| Mask more fields | `PERSONAL_FIELDS_TO_REDACT` in `sanitizer.py` (masking and restoring both use it) — extend `test/test_sanitizer.py` |
| Change limits | `AI_RATE_LIMIT_PER_HOUR` / `AI_RATE_LIMIT_PER_DAY` / `FREE_IMPORT_LIMIT` settings |
| Add an AI endpoint | A function in `services/ai/` (mask first), a request schema in `schemas/ai_schemas.py` with size limits, a route in `routers/ai.py` using `Depends(enforce_ai_quota)` and `async with ai_errors(...)`, a test in `test/test_ai.py` with `FakeOpenAI`, and a client method in the frontend's `src/lib/api.ts` |
