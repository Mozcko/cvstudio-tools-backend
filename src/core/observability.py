"""Error reporting (Sentry). Off unless SENTRY_DSN is set."""

import logging
import os
from typing import Any

from src.core.config import settings

logger = logging.getLogger(__name__)

# Never leave the server: credentials and anything a user typed or uploaded
SENSITIVE_HEADERS = {"authorization", "cookie", "set-cookie", "stripe-signature", "svix-signature", "x-api-key"}


def scrub_event(event: dict[str, Any], hint: dict[str, Any] | None = None) -> dict[str, Any]:
    """
    Last line of defence before an event is sent: drop request bodies (CV content, job
    descriptions), cookies, credentials and user details. The SDK is also configured not to
    collect them; this guarantees it even if an integration changes its defaults.
    """
    request = event.get("request")
    if isinstance(request, dict):
        request.pop("data", None)
        request.pop("cookies", None)
        request.pop("query_string", None)
        headers = request.get("headers")
        if isinstance(headers, dict):
            request["headers"] = {k: v for k, v in headers.items() if k.lower() not in SENSITIVE_HEADERS}

    user = event.get("user")
    if isinstance(user, dict):
        # The Clerk id is enough to investigate; no email, IP or name
        event["user"] = {"id": user["id"]} if user.get("id") else {}

    return event


def init_error_reporting() -> bool:
    """Starts Sentry when a DSN is configured. Returns whether it was started."""
    if not settings.SENTRY_DSN:
        return False

    import sentry_sdk

    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        environment=settings.ENVIRONMENT,
        release=os.environ.get("RAILWAY_GIT_COMMIT_SHA") or os.environ.get("RELEASE"),
        send_default_pii=False,
        # Stack-frame variables would include CV data and prompts
        include_local_variables=False,
        max_request_body_size="never",
        # Errors only; no performance tracing
        traces_sample_rate=0.0,
        before_send=scrub_event,
    )
    logger.info("Error reporting enabled")
    return True
