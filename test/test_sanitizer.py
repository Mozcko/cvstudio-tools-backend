from src.utils.sanitizer import mask_cv_pii, restore_cv_pii

def make_cv():
    return {
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

def test_mask_cv_pii_removes_sensitive_data():
    """
    Unit test to verify that sensitive PII is correctly redacted
    while leaving professional data intact.
    """
    mock_cv_data = make_cv()

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

def test_mask_tolerates_missing_or_odd_personal():
    assert mask_cv_pii({}) == {}
    assert mask_cv_pii({"personal": None}) == {"personal": None}
    assert mask_cv_pii({"mode": "markdown", "markdown": "# x"}) == {"mode": "markdown", "markdown": "# x"}

def test_restore_round_trip():
    original = make_cv()
    processed = mask_cv_pii(original)
    processed["personal"]["role"] = "Staff Engineer"  # what the model changed

    restored = restore_cv_pii(original, processed)

    assert restored["personal"]["email"] == "jane.doe@example.com"
    assert restored["personal"]["phone"] == "+1234567890"
    assert restored["personal"]["city"] == "Mexico City"
    assert [s["url"] for s in restored["personal"]["socials"]] == [
        "https://linkedin.com/in/janedoe",
        "https://github.com/janedoe",
    ]
    assert restored["personal"]["role"] == "Staff Engineer"
    assert "[REDACTED_PII]" not in str(restored)

def test_restore_overrides_values_the_model_invented():
    original = make_cv()
    processed = mask_cv_pii(original)
    processed["personal"]["email"] = "attacker@example.com"
    processed["personal"]["socials"] = [{"network": "LinkedIn", "url": "https://evil.example"}]

    restored = restore_cv_pii(original, processed)

    assert restored["personal"]["email"] == "jane.doe@example.com"
    assert restored["personal"]["socials"] == original["personal"]["socials"]
