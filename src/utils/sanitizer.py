import copy
import re
from typing import Any

REDACTED = "[REDACTED_PII]"
PERSONAL_FIELDS_TO_REDACT = ["email", "phone", "city", "address"]


def mask_cv_pii(cv_data: dict[str, Any]) -> dict[str, Any]:
    """
    Deeply copies the CV data and redacts sensitive PII fields
    before sending to external LLM services.
    """
    # Create a deep copy to avoid mutating the original data
    sanitized_data = copy.deepcopy(cv_data)

    personal = sanitized_data.get("personal")
    if isinstance(personal, dict):
        # Redact common PII fields
        for field in PERSONAL_FIELDS_TO_REDACT:
            if field in personal and personal[field]:
                personal[field] = REDACTED

        # Redact social links URLs
        if "socials" in personal and isinstance(personal["socials"], list):
            for social in personal["socials"]:
                if isinstance(social, dict) and "url" in social:
                    social["url"] = REDACTED

    return sanitized_data


def restore_cv_pii(original: dict[str, Any], processed: dict[str, Any]) -> dict[str, Any]:
    """
    Puts the fields redacted by `mask_cv_pii` back into data returned by the LLM,
    taking the real values from the original CV. Returns a new dict.
    """
    restored = copy.deepcopy(processed)
    original_personal = original.get("personal")
    if not isinstance(original_personal, dict):
        return restored

    personal = restored.get("personal")
    if not isinstance(personal, dict):
        return restored

    for field in PERSONAL_FIELDS_TO_REDACT:
        if field in original_personal:
            personal[field] = original_personal[field]
        elif personal.get(field) == REDACTED:
            personal.pop(field, None)

    original_socials = original_personal.get("socials")
    socials = personal.get("socials")
    if isinstance(original_socials, list):
        same_shape = (
            isinstance(socials, list)
            and len(socials) == len(original_socials)
            and all(isinstance(s, dict) for s in socials)
        )
        if same_shape:
            for social, original_social in zip(socials, original_socials, strict=False):
                if isinstance(original_social, dict) and "url" in original_social:
                    social["url"] = original_social["url"]
        else:
            # The model added, dropped or mangled links: keep the user's own list
            personal["socials"] = copy.deepcopy(original_socials)

    return restored


# --- Free text (documents a user imports) ---------------------------------------------------

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
URL_RE = re.compile(r"(?:https?://|www\.)[^\s<>\"')\]]+", re.IGNORECASE)
# Digits joined by single separators; " - " between two numbers (a date range) does not match
PHONE_RE = re.compile(r"(?<![\w/])\+?\(?\d(?:[ .\-]?[()]?[ ]?\d){8,14}(?![\w/])")
PLACEHOLDER_RE = re.compile(r"\[\[(?:EMAIL|LINK|PHONE)_\d+\]\]")
YEAR_RE = re.compile(r"(?:19|20)\d{2}")


def _looks_like_dates(candidate: str) -> bool:
    """True for things like "2019 2023" or "2019-01 2023-06" that the phone pattern also matches."""
    groups = re.findall(r"\d+", candidate)
    years = [g for g in groups if len(g) == 4 and YEAR_RE.fullmatch(g)]
    return len(years) >= 2 and all(len(g) in (1, 2, 4) for g in groups)


def mask_text_pii(text: str) -> tuple[str, dict[str, str]]:
    """
    Replaces e-mail addresses, links and phone numbers in free text with placeholders such as
    `[[EMAIL_1]]`. Returns the masked text and the placeholder → original value mapping needed
    by `restore_text_pii`.
    """
    mapping: dict[str, str] = {}
    seen: dict[str, str] = {}

    def replacer(kind: str, keep=None):
        def replace(match: re.Match) -> str:
            value = match.group(0)
            if keep is not None and keep(value):
                return value
            if value not in seen:
                placeholder = f"[[{kind}_{sum(1 for k in mapping if k.startswith(f'[[{kind}_')) + 1}]]"
                seen[value] = placeholder
                mapping[placeholder] = value
            return seen[value]

        return replace

    # Placeholder-looking text in the document itself must not be mistaken for ours later
    masked = PLACEHOLDER_RE.sub("", text)
    masked = EMAIL_RE.sub(replacer("EMAIL"), masked)
    masked = URL_RE.sub(replacer("LINK"), masked)
    masked = PHONE_RE.sub(replacer("PHONE", keep=_looks_like_dates), masked)
    return masked, mapping


def restore_text_pii(value: Any, mapping: dict[str, str]) -> Any:
    """Puts the original values back into every string of a JSON-like structure (returns a copy)."""
    if isinstance(value, str):
        restored = PLACEHOLDER_RE.sub(lambda m: mapping.get(m.group(0), ""), value)
        return restored.strip() if restored != value else value
    if isinstance(value, list):
        return [restore_text_pii(item, mapping) for item in value]
    if isinstance(value, dict):
        return {key: restore_text_pii(item, mapping) for key, item in value.items()}
    return value
