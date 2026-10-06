import copy
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
