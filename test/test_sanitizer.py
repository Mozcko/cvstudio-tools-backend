from src.utils.sanitizer import mask_cv_pii

def test_mask_cv_pii_removes_sensitive_data():
    """
    Unit test to verify that sensitive PII is correctly redacted 
    while leaving professional data intact.
    """
    mock_cv_data = {
        "personal": {
            "name": "Jane Doe",
            "role": "Senior Engineer",
            "email": "jane.doe@example.com",
            "phone": "+1234567890",
            "city": "Mexico City",
            "socials": [
                {"network": "LinkedIn", "url": "https://linkedin.com/in/janedoe"},
                {"network": "GitHub", "url": "https://github.com/janedoe"}
            ]
        },
        "experience": [
            {
                "company": "Tech Corp",
                "role": "Lead Developer",
                "description": ["Led a team of 10", "Built scalable APIs"]
            }
        ]
    }

    sanitized = mask_cv_pii(mock_cv_data)

    # Verify Redactions
    assert sanitized["personal"]["email"] == "[REDACTED_PII]"
    assert sanitized["personal"]["phone"] == "[REDACTED_PII]"
    assert sanitized["personal"]["city"] == "[REDACTED_PII]"
    assert sanitized["personal"]["socials"][0]["url"] == "[REDACTED_PII]"
    assert sanitized["personal"]["socials"][1]["url"] == "[REDACTED_PII]"

    # Verify Non-Sensitive Data Intact
    assert sanitized["personal"]["name"] == "Jane Doe"
    assert sanitized["personal"]["role"] == "Senior Engineer"
    assert sanitized["experience"][0]["company"] == "Tech Corp"
    
    # Verify Deep Copy (original unchanged)
    assert mock_cv_data["personal"]["email"] == "jane.doe@example.com"
