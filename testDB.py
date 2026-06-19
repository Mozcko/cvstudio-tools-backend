import asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from src.models.cv import CV

# We need the correct DB URL. Let's find it.
import os
from dotenv import load_dotenv
load_dotenv()
db_url = os.environ.get("DATABASE_URL")
if not db_url:
    print("NO DB URL")
    exit(1)

engine = create_async_engine(db_url)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def test():
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(CV))
        cvs = result.scalars().all()
        for cv in cvs:
            print(f"CV ID: {cv.id}, Title: {cv.title}, Content Type: {type(cv.content)}, Content Mode: {cv.content.get('mode', 'No Mode')}")

asyncio.run(test())
