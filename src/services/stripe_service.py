import stripe
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.core.config import settings
from src.models.user import User
from datetime import datetime, timedelta, timezone

async def process_webhook_event(payload: bytes, sig_header: str, db: AsyncSession):
    if not settings.STRIPE_WEBHOOK_SECRET:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Stripe webhook secret not configured"
        )

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        # Invalid payload
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        # Invalid signature
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid signature")

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        
        # Extract Clerk User ID from client_reference_id or metadata
        clerk_user_id = session.get("client_reference_id") or session.get("metadata", {}).get("user_id")
        plan_duration = session.get("metadata", {}).get("plan_duration")
        
        if clerk_user_id:
            # Calculate expiration date
            expires_at = None
            if plan_duration in ["7", "30"]:
                expires_at = datetime.now(timezone.utc) + timedelta(days=int(plan_duration))
            
            # Update user's is_pro status and expiration
            result = await db.execute(select(User).where(User.id == clerk_user_id))
            user = result.scalar_one_or_none()
            
            if user:
                user.is_pro = True
                user.pro_expires_at = expires_at
                await db.commit()
            else:
                # If user doesn't exist in our DB yet, we create it
                new_user = User(id=clerk_user_id, is_pro=True, pro_expires_at=expires_at)
                db.add(new_user)
                await db.commit()
    
    return {"status": "success"}
