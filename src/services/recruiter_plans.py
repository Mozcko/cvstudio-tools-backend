"""
Recruiter plans: what each allows, whether a user may evaluate another CV right now, and
keeping a subscription in step with Stripe.

  starter     STRIPE_PRICE_RECRUITER_STARTER   RECRUITER_STARTER_MONTHLY CVs per billing month
  pro         STRIPE_PRICE_RECRUITER_PRO       RECRUITER_PRO_MONTHLY CVs per billing month
  enterprise  agreed by hand (grant_recruiter)  unlimited unless a quota was agreed
  (none)      free trial                        RECRUITER_TRIAL_CVS CVs in total, once
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.models.ai_request import AIRequest
from src.models.recruiter import RecruiterSubscription
from src.models.user import User

RecruiterPlan = Literal["starter", "pro", "enterprise"]

# One row in ai_requests per CV evaluated
USAGE_KEY = "recruiter:evaluate"
# Plans without a Stripe billing period count usage over this rolling window
MANUAL_WINDOW = timedelta(days=30)

TRIAL_USED_DETAIL = "The free trial is used up. Choose a plan to evaluate more CVs."
QUOTA_DETAIL = "This month's CV allowance is used up. It renews with your next billing period."
PAST_DUE_DETAIL = "The last payment failed. Update your payment method to keep evaluating CVs."
ENDED_DETAIL = "Your recruiter plan has ended. Choose a plan to evaluate more CVs."


def price_to_plan() -> dict[str, RecruiterPlan]:
    prices = {
        settings.STRIPE_PRICE_RECRUITER_STARTER: "starter",
        settings.STRIPE_PRICE_RECRUITER_PRO: "pro",
    }
    return {price: plan for price, plan in prices.items() if price}


def plan_monthly_limit(plan: str) -> int | None:
    """CVs per period; None is unlimited."""
    return {"starter": settings.RECRUITER_STARTER_MONTHLY, "pro": settings.RECRUITER_PRO_MONTHLY}.get(plan)


@dataclass
class Entitlement:
    # trial | starter | pro | enterprise
    plan: str
    # active | past_due | canceled | trial
    status: str
    can_evaluate: bool
    used: int
    # None is unlimited
    limit: int | None
    remaining: int | None
    period_end: datetime | None
    retention_days: int
    # Why evaluating is refused, when it is
    reason: str | None = None
    has_billing: bool = False


async def get_subscription(db: AsyncSession, user_id: str) -> RecruiterSubscription | None:
    result = await db.execute(select(RecruiterSubscription).where(RecruiterSubscription.user_id == user_id))
    return result.scalar_one_or_none()


def _is_running(sub: RecruiterSubscription, now: datetime) -> bool:
    """Paid up, or within what was already paid for."""
    return sub.status == "active" and (sub.current_period_end is None or sub.current_period_end > now)


async def _used_since(db: AsyncSession, user_id: str, since: datetime | None) -> int:
    query = select(func.count()).where(AIRequest.user_id == user_id, AIRequest.endpoint == USAGE_KEY)
    if since is not None:
        query = query.where(AIRequest.created_at >= since)
    return (await db.execute(query)).scalar_one()


async def entitlement(db: AsyncSession, user: User, now: datetime | None = None) -> Entitlement:
    """What the user's recruiter plan allows at this moment."""
    now = now or datetime.now(UTC)
    sub = await get_subscription(db, user.id)

    if sub is None or not (_is_running(sub, now) or sub.status == "past_due"):
        # No plan (or one that ended): what is left of the one-off trial
        used = await _used_since(db, user.id, None)
        ended = sub is not None
        # Evaluations made while subscribed do not bring the trial back, nor count against it
        limit = 0 if ended else settings.RECRUITER_TRIAL_CVS
        remaining = max(0, limit - used)
        return Entitlement(
            plan=sub.plan if ended else "trial",
            status="canceled" if ended else "trial",
            can_evaluate=remaining > 0,
            used=used if not ended else 0,
            limit=limit,
            remaining=remaining,
            period_end=sub.current_period_end if ended else None,
            retention_days=(sub.retention_days if ended and sub.retention_days else settings.RECRUITER_RETENTION_DAYS),
            reason=None if remaining > 0 else (ENDED_DETAIL if ended else TRIAL_USED_DETAIL),
            has_billing=bool(ended and sub.stripe_customer_id),
        )

    # Stripe-billed plans count per billing period; plans agreed by hand over a rolling month
    window_start = sub.current_period_start if sub.stripe_subscription_id else now - MANUAL_WINDOW
    used = await _used_since(db, user.id, window_start)
    limit = sub.monthly_quota if sub.monthly_quota is not None else plan_monthly_limit(sub.plan)
    remaining = None if limit is None else max(0, limit - used)

    reason = None
    if sub.status == "past_due":
        reason = PAST_DUE_DETAIL
    elif remaining == 0:
        reason = QUOTA_DETAIL

    return Entitlement(
        plan=sub.plan,
        status=sub.status,
        can_evaluate=reason is None,
        used=used,
        limit=limit,
        remaining=remaining,
        period_end=sub.current_period_end,
        retention_days=sub.retention_days or settings.RECRUITER_RETENTION_DAYS,
        reason=reason,
        has_billing=bool(sub.stripe_customer_id),
    )


async def reserve_evaluation(db: AsyncSession, user: User) -> uuid.UUID:
    """
    Records one CV evaluation against the user's allowance, or refuses with 403.
    Returns the usage row's id so a failed evaluation can be given back.
    """
    allowed = await entitlement(db, user)
    if not allowed.can_evaluate:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=allowed.reason)
    usage = AIRequest(id=uuid.uuid4(), user_id=user.id, endpoint=USAGE_KEY)
    db.add(usage)
    await db.commit()
    return usage.id


async def release_evaluation(db: AsyncSession, usage_id: uuid.UUID) -> None:
    await db.execute(delete(AIRequest).where(AIRequest.id == usage_id))
    await db.commit()


# ── Stripe ────────────────────────────────────────────────────────────────────

# Stripe's subscription states, reduced to what matters here. "incomplete" (first payment not
# made yet) is deliberately absent: nothing is granted until Stripe says the subscription is on.
STRIPE_STATUS = {
    "active": "active",
    "trialing": "active",
    "past_due": "past_due",
    "unpaid": "past_due",
    "canceled": "canceled",
    "incomplete_expired": "canceled",
}


def _timestamp(value) -> datetime | None:
    return datetime.fromtimestamp(value, UTC) if isinstance(value, int | float) and value > 0 else None


def _first_item(subscription: dict) -> dict:
    items = (subscription.get("items") or {}).get("data") or []
    return items[0] if items and isinstance(items[0], dict) else {}


def _period(subscription: dict) -> tuple[datetime | None, datetime | None]:
    """Billing period. Newer Stripe API versions report it on the item instead of the subscription."""
    item = _first_item(subscription)
    start = _timestamp(subscription.get("current_period_start")) or _timestamp(item.get("current_period_start"))
    end = _timestamp(subscription.get("current_period_end")) or _timestamp(item.get("current_period_end"))
    return start, end


async def apply_stripe_subscription(
    db: AsyncSession, subscription: dict, event_created: int | None, deleted: bool = False
) -> None:
    """Makes our row say what Stripe says about a subscription. Safe to call for the same event twice."""
    user_id = (subscription.get("metadata") or {}).get("user_id")
    subscription_id = subscription.get("id")
    if not subscription_id:
        return

    sub = None
    if user_id:
        sub = await get_subscription(db, user_id)
    if sub is None:
        found = await db.execute(
            select(RecruiterSubscription).where(RecruiterSubscription.stripe_subscription_id == subscription_id)
        )
        sub = found.scalar_one_or_none()

    new_status = "canceled" if deleted else STRIPE_STATUS.get(subscription.get("status") or "")
    plan = price_to_plan().get((_first_item(subscription).get("price") or {}).get("id"))
    if new_status is None or (sub is None and (not user_id or plan is None or new_status == "canceled")):
        # Not paid for yet, not one of our prices, nobody to attach it to, or the end of a
        # subscription we never knew (which must not cost the user their free trial)
        return

    event_at = _timestamp(event_created) or datetime.now(UTC)
    if sub is not None:
        if sub.stripe_subscription_id and sub.stripe_subscription_id != subscription_id:
            # News about an older subscription must not disturb the current one
            if new_status == "canceled" or sub.status != "canceled":
                return
        if sub.last_event_at and event_at < sub.last_event_at:
            return
    else:
        if not (await db.execute(select(User.id).where(User.id == user_id))).first():
            # The user row must exist before the subscription that points at it
            db.add(User(id=user_id, is_pro=False))
            await db.flush()
        sub = RecruiterSubscription(user_id=user_id, plan=plan, status=new_status)
        db.add(sub)

    start, end = _period(subscription)
    sub.stripe_subscription_id = subscription_id
    sub.stripe_customer_id = subscription.get("customer") or sub.stripe_customer_id
    sub.status = new_status
    if plan:
        sub.plan = plan
    if start:
        sub.current_period_start = start
    if end:
        sub.current_period_end = end
    sub.last_event_at = event_at
    await db.commit()
