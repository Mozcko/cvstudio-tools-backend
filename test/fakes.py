"""Throwaway values for tests. Nothing here is, or looks like, a real credential in the repository."""

import base64
import secrets


def random_signing_secret() -> str:
    """A webhook signing secret in the provider's format, generated fresh for each test run.

    Generated instead of hardcoded so that no secret-shaped literal is committed
    (secret scanners cannot tell a made-up `whsec_...` value from a real one).
    """
    return "whsec_" + base64.b64encode(secrets.token_bytes(24)).decode()
