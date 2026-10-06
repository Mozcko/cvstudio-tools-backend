import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from svix.webhooks import Webhook, WebhookVerificationError

from src.api.dependencies import get_db
from src.core.config import settings
from src.models.cv import CV
from src.models.user import User
from src.services.stripe_service import process_webhook_event

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


@router.post("/stripe")
async def stripe_webhook(request: Request, stripe_signature: str = Header(None), db: AsyncSession = Depends(get_db)):
    if not stripe_signature:
        raise HTTPException(status_code=400, detail="Missing Stripe-Signature header")

    # Read raw body for signature verification
    payload = await request.body()

    # Process event
    result = await process_webhook_event(payload, stripe_signature, db)

    return result


def _primary_email(data: dict[str, Any]) -> str | None:
    addresses = data.get("email_addresses") or []
    primary_id = data.get("primary_email_address_id")
    for address in addresses:
        if isinstance(address, dict) and address.get("id") == primary_id:
            return address.get("email_address")
    for address in addresses:
        if isinstance(address, dict) and address.get("email_address"):
            return address["email_address"]
    return None


@router.post("/clerk")
async def clerk_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Handles Clerk webhooks (delivered through Svix, which signs every request).
    - 'user.created' / 'user.updated': keep the user's email in sync.
    - 'user.deleted': purge the user's data ('Right to Erasure').
    """
    if not settings.CLERK_WEBHOOK_SECRET:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Clerk webhook secret not configured"
        )

    raw_body = await request.body()
    try:
        Webhook(settings.CLERK_WEBHOOK_SECRET).verify(raw_body, dict(request.headers))
        payload = json.loads(raw_body)
    except WebhookVerificationError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid signature") from None
    except ValueError:
        # Correctly signed but not JSON (the Svix library also parses the body)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid payload") from None

    if not isinstance(payload, dict):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid payload")

    event_type = payload.get("type")
    data = payload.get("data") or {}
    user_id = data.get("id")

    if not user_id:
        return {"status": "success"}

    if event_type == "user.deleted":
        # CVs also go through ON DELETE CASCADE; the explicit delete keeps this
        # correct on databases that predate that constraint.
        await db.execute(delete(CV).where(CV.user_id == user_id))
        await db.execute(delete(User).where(User.id == user_id))
        await db.commit()

    elif event_type in ("user.created", "user.updated"):
        email = _primary_email(data)
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            user = User(id=user_id, is_pro=False)
            db.add(user)
        user.email = email
        try:
            await db.commit()
        except IntegrityError:
            # Email already attached to another row (e.g. an account that was re-created)
            await db.rollback()
            logger.warning("Could not store email for user %s: already in use", user_id)

    return {"status": "success"}
