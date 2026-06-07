from fastapi import APIRouter, Request, Header, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from src.api.dependencies import get_db
from src.services.stripe_service import process_webhook_event
from src.models.user import User
from src.models.cv import CV

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])

@router.post("/stripe")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(None),
    db: AsyncSession = Depends(get_db)
):
    if not stripe_signature:
        raise HTTPException(status_code=400, detail="Missing Stripe-Signature header")

    # Read raw body for signature verification
    payload = await request.body()
    
    # Process event
    result = await process_webhook_event(payload, stripe_signature, db)
    
    return result

@router.post("/clerk")
async def clerk_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Handles Clerk webhooks. Specifically listens for 'user.deleted' to ensure 
    compliance with 'Right to Erasure' by purging user data from our DB.
    """
    payload = await request.json()
    event_type = payload.get("type")
    
    if event_type == "user.deleted":
        user_id = payload.get("data", {}).get("id")
        if user_id:
            # Delete user's CVs first
            await db.execute(delete(CV).where(CV.user_id == user_id))
            # Delete user record
            await db.execute(delete(User).where(User.id == user_id))
            await db.commit()
            
    return {"status": "success"}
