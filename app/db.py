# app/db.py
import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "").split("?")[0]  # ⬅️ on enlève toute query (?sslmode=...)
# IMPORTANT: forcer SSL côté asyncpg proprement
engine = create_async_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    connect_args={"ssl": True},   # ⬅️ c'est ce que asyncpg attend
)

SessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)

async def get_db():
    async with SessionLocal() as session:
        yield session

