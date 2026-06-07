import copy
from typing import Any, Dict

def mask_cv_pii(cv_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deeply copies the CV data and redacts sensitive PII fields 
    before sending to external LLM services.
    """
    # Create a deep copy to avoid mutating the original data
    sanitized_data = copy.deepcopy(cv_data)
    
    if "personal" in sanitized_data:
        personal = sanitized_data["personal"]
        
        # Redact common PII fields
        fields_to_redact = ["email", "phone", "city", "address"]
        for field in fields_to_redact:
            if field in personal and personal[field]:
                personal[field] = "[REDACTED_PII]"
        
        # Redact social links URLs
        if "socials" in personal and isinstance(personal["socials"], list):
            for social in personal["socials"]:
                if isinstance(social, dict) and "url" in social:
                    social["url"] = "[REDACTED_PII]"
                    
    return sanitized_data
