import asyncio
import argparse
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from src.models.promo import PromoCode
import os
from dotenv import load_dotenv

load_dotenv()

async def create_promo_code(code: str, max_uses: int, granted_days: int):
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("Error: DATABASE_URL not found in environment.")
        return

    # Automatically adapt the URL for asyncpg if running in environments like Railway/Heroku
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    engine = create_async_engine(db_url)
    AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with AsyncSessionLocal() as session:
        new_promo = PromoCode(
            code=code,
            max_uses=max_uses,
            granted_days=granted_days
        )
        session.add(new_promo)
        try:
            await session.commit()
            print(f"✅ Successfully created promo code: {code}")
            print(f"   Max Uses: {max_uses}")
            print(f"   Granted Days: {granted_days} {'(Lifetime)' if granted_days >= 9999 else ''}")
        except Exception as e:
            await session.rollback()
            print(f"❌ Failed to create promo code. Error: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate a new Promotional Code")
    parser.add_argument("--code", type=str, required=True, help="The string code to redeem (e.g. LIFETIME2026)")
    parser.add_argument("--uses", type=int, default=1, help="Maximum number of times this code can be used")
    parser.add_argument("--days", type=int, default=30, help="Number of premium days granted (9999 for lifetime)")
    
    args = parser.parse_args()
    
    # Needs to be run inside an event loop
    asyncio.run(create_promo_code(args.code, args.uses, args.days))
