import argparse
import asyncio
import os
import sys
from datetime import UTC, datetime, timedelta

# Add src to path so we can import internal modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from sqlalchemy import select

from src.db.database import AsyncSessionLocal
from src.models.recruiter import RecruiterSubscription
from src.models.user import User


async def grant_recruiter(
    user_id: str,
    plan: str = "enterprise",
    months: int | None = None,
    quota: int | None = None,
    retention_days: int | None = None,
    revoke: bool = False,
) -> int:
    """
    Gives a user a recruiter plan agreed outside Stripe (Enterprise), or takes it away.
    `months=None` is open-ended; `quota=None` uses the plan's own limit (unlimited for Enterprise).
    """
    async with AsyncSessionLocal() as session:
        if not (await session.execute(select(User.id).where(User.id == user_id))).first():
            print("User not found in local DB. Creating new user record...")
            session.add(User(id=user_id, is_pro=False))
            await session.flush()

        result = await session.execute(select(RecruiterSubscription).where(RecruiterSubscription.user_id == user_id))
        sub = result.scalar_one_or_none()

        if sub and sub.stripe_subscription_id and sub.status in ("active", "past_due"):
            print("Error: this user has a running Stripe subscription. Cancel it in Stripe first.")
            return 1

        if revoke:
            if not sub:
                print("Error: this user has no recruiter plan.")
                return 1
            sub.status = "canceled"
            await session.commit()
            print(f"Recruiter plan of {user_id} ended.")
            return 0

        now = datetime.now(UTC)
        if not sub:
            sub = RecruiterSubscription(user_id=user_id, plan=plan, status="active")
            session.add(sub)
        sub.plan = plan
        sub.status = "active"
        sub.stripe_subscription_id = None
        sub.current_period_start = now
        sub.current_period_end = now + timedelta(days=30 * months) if months else None
        sub.monthly_quota = quota
        sub.retention_days = retention_days
        await session.commit()

        until = sub.current_period_end.date().isoformat() if sub.current_period_end else "open-ended"
        print(f"Recruiter plan granted: {user_id} -> {plan}, until {until}")
        print(f"   CVs per month: {quota if quota is not None else 'plan default'}")
        print(f"   Retention days: {retention_days if retention_days is not None else 'default'}")
        return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Grant or end a recruiter plan agreed outside Stripe.")
    parser.add_argument("--user-id", type=str, required=True, help="The Clerk User ID")
    parser.add_argument("--plan", choices=["starter", "pro", "enterprise"], default="enterprise")
    parser.add_argument("--months", type=int, default=None, help="How long it lasts (omit for open-ended)")
    parser.add_argument("--quota", type=int, default=None, help="CVs per month (omit for the plan default)")
    parser.add_argument("--retention-days", type=int, default=None, help="Days candidate data is kept")
    parser.add_argument("--revoke", action="store_true", help="End the plan instead of granting it")
    args = parser.parse_args()

    sys.exit(
        asyncio.run(grant_recruiter(args.user_id, args.plan, args.months, args.quota, args.retention_days, args.revoke))
    )
