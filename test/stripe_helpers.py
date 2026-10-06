"""Build webhook requests exactly as Stripe signs them, so tests go through the real SDK check."""

import hashlib
import hmac
import json
import time

from src.core.config import settings


def signed_stripe_request(event, secret: str | None = None) -> tuple[bytes, dict]:
    """Returns (body, headers) for POST /webhooks/stripe. `event` may be a dict or a raw string."""
    body = event if isinstance(event, str) else json.dumps(event)
    timestamp = int(time.time())
    signature = hmac.new(
        (secret or settings.STRIPE_WEBHOOK_SECRET).encode(), f"{timestamp}.{body}".encode(), hashlib.sha256
    ).hexdigest()
    return body.encode(), {"Stripe-Signature": f"t={timestamp},v1={signature}"}
