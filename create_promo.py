import asyncio
import argparse

from src.db.database import AsyncSessionLocal
from src.models.promo import PromoCode
from src.services.pro import LIFETIME_DAYS

async def create_promo_code(code: str, max_uses: int, granted_days: int):
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
            print(f"   Granted Days: {granted_days} {'(Lifetime)' if granted_days >= LIFETIME_DAYS else ''}")
        except Exception as e:
            await session.rollback()
            print(f"❌ Failed to create promo code. Error: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate a new Promotional Code")
    parser.add_argument("--code", type=str, required=True, help="The string code to redeem (e.g. LIFETIME2026)")
    parser.add_argument("--uses", type=int, default=1, help="Maximum number of times this code can be used (0 = unlimited)")
    parser.add_argument("--days", type=int, default=30, help="Number of premium days granted (9999 for lifetime)")

    args = parser.parse_args()

    # Needs to be run inside an event loop
    asyncio.run(create_promo_code(args.code.strip(), args.uses, args.days))
