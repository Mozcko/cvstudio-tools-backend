import argparse
import asyncio
import os
import sys

# Add src to path so we can import internal modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from sqlalchemy import select

from src.db.database import AsyncSessionLocal
from src.models.user import User
from src.services.pro import grant_pro


async def upgrade_user(user_id: str = None, email: str = None, days: int = None, premium: bool = False):
    """
    Manually grants Pro to a user. `days=None` means lifetime; otherwise the
    time is added on top of whatever the user has left.
    """
    async with AsyncSessionLocal() as session:
        query = select(User)
        if user_id:
            query = query.where(User.id == user_id)
        elif email:
            query = query.where(User.email == email)
        else:
            print("Error: Must provide either --user-id or --email")
            return 1

        result = await session.execute(query)
        user = result.scalar_one_or_none()

        if not user:
            if not user_id:
                # Emails are only known once Clerk's user webhook has delivered them
                print(f"Error: no user with email {email}. Use --user-id with the Clerk user ID instead.")
                return 1
            # User hasn't made a request yet but we want to grant Pro
            print("User not found in local DB. Creating new user record...")
            user = User(id=user_id, is_pro=False)
            session.add(user)

        grant_pro(user, days, premium=premium)
        await session.commit()

        until = user.pro_expires_at.isoformat() if user.pro_expires_at else "lifetime"
        print(f"Successfully upgraded user: {user.id} ({user.email}) - Pro until: {until}")
        return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Manually upgrade a CVStudio user to Pro tier.")
    parser.add_argument("--user-id", type=str, help="The Clerk User ID")
    parser.add_argument("--email", type=str, help="The user email address")
    parser.add_argument("--days", type=int, default=None, help="Days of Pro to grant (omit for lifetime)")
    parser.add_argument(
        "--premium", action="store_true", help="Also grant the premium level for those days (lifetime always has it)"
    )

    args = parser.parse_args()

    if not args.user_id and not args.email:
        parser.print_help()
        sys.exit(1)

    sys.exit(asyncio.run(upgrade_user(user_id=args.user_id, email=args.email, days=args.days, premium=args.premium)))
