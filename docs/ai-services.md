# AI Services

Code: `src/services/ai/`, exposed by `src/api/routers/ai.py`. All three endpoints are Pro-only.

## Provider and model

`src/services/ai/base.py` builds two `AsyncOpenAI` clients at import time, one for OpenAI and one
for DeepSeek (an OpenAI-compatible API), each only if its key is set.

`get_ai_client(provider="openai")` returns `(client, model)`:

| Provider requested | Returns |
| :--- | :--- |
| `"openai"` (the default, and what every caller passes) | OpenAI client, `gpt-4o-mini` |
| `"deepseek"` with a DeepSeek key | DeepSeek client, `deepseek-chat` |
| anything, with no OpenAI key | `ValueError("OpenAI API key is missing.")` |

In practice **every feature runs on OpenAI `gpt-4o-mini`**. DeepSeek is configured but never
selected, and there is no fallback between providers. The model name is hardcoded here; changing
models is a one-line edit in `base.py`.

No temperature, token limit, timeout or retry is set on any call — SDK defaults apply.

## PII masking (`src/utils/sanitizer.py`)

`mask_cv_pii(cv_data)` deep-copies the CV and replaces these with `"[REDACTED_PII]"`:

- `personal.email`, `personal.phone`, `personal.city`, `personal.address`
- every `personal.socials[].url`

It does **not** touch `personal.name`, the summary, or anything in experience, education, projects
or custom sections.

| Feature | Masked before the LLM call? |
| :--- | :--- |
| ATS simulation | ✅ |
| Cover letter | ✅ |
| Improve / optimize / translate | ❌ — the CV travels as a string in `text` and is sent as is |

## The three features

### Improve, optimize, translate — `improve_text(text, context)`

`improvement.py`. One function serves three frontend actions. It decides what to do by searching the
lower-cased `context` string for keywords:

| Detected when `context` contains | Mode |
| :--- | :--- |
| `translate` | Translation |
| `optimize` **and** `, jd: ` followed by text | Job-targeted optimisation |
| otherwise | General rewrite ("enhance") |

- **Target language** comes from `lang: es` / `lang: en` / `lang: pt`; otherwise "the original
  language of the input".
- **Job description** is everything after the first `jd: `. It is interpolated into the **system
  prompt**.
- **JSON mode**: if `text` starts with `{`, an instruction is appended to return the same JSON
  structure and the call uses `response_format={"type": "json_object"}`.

The frontend always sends the whole CV as JSON in `text` and
`"Action: <action>, Lang: <lang>, JD: <jd>"` in `context`, then parses `improved_text` and merges
it defensively over the user's data (see the frontend's `docs/auth-billing-ai.md`).

System prompt intent per mode:

- *Translation* — 1:1 translation into the target language, keep the exact number of items in every
  section, do not translate proper names.
- *Optimisation* — weave the job description's keywords into summary, experience and skills;
  preserve content; respond entirely in the target language.
- *Enhance* — more professional, impactful, metric-driven wording with strong action verbs; keep
  the meaning.

### ATS simulation — `simulate_ats(cv_data, job_description)`

`ats.py`. Masks PII, then asks for a JSON object with a fixed structure (score, interview
probability, tier, per-requirement analysis, missing keywords, improvement actions) in JSON mode.
Returns `json.loads` of the reply without validating it. The output language is not specified, so
the analysis comes back in whatever language the model chooses.

### Cover letter — `generate_cover_letter(cv_data, job_description)`

`cover_letter.py`. The interesting part is how it keeps contact details away from the model:

1. Read `name`, `email`, `phone`, `city` from the **unmasked** CV.
2. Mask the CV and ask the model for the letter **body only**, starting at the salutation.
3. Build the header in Python — name, city, email, phone, today's date — and prepend it.

The date is formatted `%B %d, %Y` in the server's locale (English month names) regardless of the
CV's language. The letter's language is not specified in the prompt.

`translation.py` contains a standalone `translate_text` helper that nothing calls.

## Error handling

Each router handler catches every exception, prints a traceback and responds `500` with
`str(exception)` as `detail`. Consequences:

- A non-Pro caller gets `500` (`"403: This feature requires a Pro subscription."`) instead of `403`.
- Provider errors, including text returned by the OpenAI SDK, are passed through to the client.

## Changing things

| Task | Where |
| :--- | :--- |
| Switch model or provider | `get_ai_client` in `base.py`; or pass `provider="deepseek"` from a service |
| Edit a prompt | The `system_prompt` in the relevant service file |
| Mask more fields | `fields_to_redact` in `sanitizer.py` — and extend `test/test_sanitizer.py` |
| Add an AI endpoint | A function in `services/ai/`, a request schema in `schemas/ai_schemas.py`, a route in `routers/ai.py` calling `check_pro_status` first, and a client method in the frontend's `src/lib/api.ts` |
