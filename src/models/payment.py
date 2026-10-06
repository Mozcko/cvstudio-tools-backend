from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.sql import func

from src.db.database import Base


class Payment(Base):
    """One row per completed Stripe Checkout session. Kept after the user is deleted."""

    __tablename__ = "payments"

    session_id = Column(String, primary_key=True)  # Stripe Checkout Session ID
    user_id = Column(String, nullable=False, index=True)
    plan = Column(String, nullable=False)  # '7' | '30' | 'lifetime'
    payment_intent = Column(String, nullable=True, index=True)
    granted_days = Column(Integer, nullable=True)  # NULL for lifetime
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    refunded_at = Column(DateTime(timezone=True), nullable=True)
