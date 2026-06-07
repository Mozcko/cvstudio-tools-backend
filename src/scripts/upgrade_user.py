import asyncio
import argparse
import sys
import os

# Add src to path so we can import internal modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from sqlalchemy import select, update
from src.db.database import AsyncSessionLocal
from src.models.user import User

async def upgrade_user(user_id: str = None, email: str = None):
    """
    Manually upgrades a user to the Pro tier in the local database.
    """
    async with AsyncSessionLocal() as session:
        query = select(User)
        if user_id:
            query = query.where(User.id == user_id)
        elif email:
            query = query.where(User.email == email)
        else:
            print("Error: Must provide either --user-id or --email")
            return

        result = await session.execute(query)
        user = result.scalar_one_or_none()

        if not user:
            # If user not found, we create them (in case they haven't logged in yet but we want to grant Pro)
            print(f"User not found in local DB. Creating new Pro user record...")
            new_user = User(id=user_id, email=email, is_pro=True)
            session.add(new_user)
            await session.commit()
            print(f"Successfully created and upgraded user: {user_id or email}")
        else:
            user.is_pro = True
            await session.commit()
            print(f"Successfully upgraded existing user: {user.id} ({user.email})")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Manually upgrade a CVStudio user to Pro tier.")
    parser.add_argument("--user-id", type=str, help="The Clerk User ID")
    parser.add_argument("--email", type=str, help="The user email address")

    args = parser.parse_args()

    if not args.user_id and not args.email:
        parser.print_help()
        sys.exit(1)

    asyncio.run(upgrade_user(user_id=args.user_id, email=args.email))
