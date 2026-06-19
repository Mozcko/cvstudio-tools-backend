import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select
from src.models.cv import CV
import os
from dotenv import load_dotenv

load_dotenv()
db_url = os.environ.get("DATABASE_URL")
engine = create_async_engine(db_url)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def run():
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(CV).where(CV.id == 'a8660759-bb04-4142-aa84-bc9627e8245a'))
        cv = result.scalar_one_or_none()
        print("CV CONTENT FROM DB OBJECT:", cv.content)

asyncio.run(run())
