from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.sql import func

from src.db.database import Base


class RecruiterSubscription(Base):
    """
    A user's recruiter plan. Starter and Pro are Stripe subscriptions and follow what Stripe
    reports; Enterprise is agreed by hand and has no Stripe ids. Independent of the job-seeker
    passes on `users`: neither grants the other.
    """

    __tablename__ = "recruiter_subscriptions"

    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    plan = Column(String, nullable=False)  # starter | pro | enterprise
    status = Column(String, nullable=False)  # active | past_due | canceled
    current_period_start = Column(DateTime(timezone=True), nullable=True)
    # End of what has been paid for; NULL for an open-ended Enterprise agreement
    current_period_end = Column(DateTime(timezone=True), nullable=True)
    stripe_customer_id = Column(String, nullable=True, index=True)
    stripe_subscription_id = Column(String, nullable=True, unique=True)
    # When Stripe produced the last event applied here, to ignore ones that arrive out of order
    last_event_at = Column(DateTime(timezone=True), nullable=True)
    # Agreed individually (Enterprise). NULL means the plan's own value
    monthly_quota = Column(Integer, nullable=True)
    retention_days = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
