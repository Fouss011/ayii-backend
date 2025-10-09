# app/db.py
import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool

# .strip() enlève ton '\n' vu dans /dev/env-db
DATABASE_URL = os.getenv("DATABASE_URL", "").strip().split("?")[0]

engine = create_async_engine(
    DATABASE_URL,                 # postgresql+asyncpg://...:6543/postgres
    poolclass=NullPool,           # évite de monopoliser le pooler Supabase
    pool_pre_ping=True,
    connect_args={
        # 🔑 clé: désactiver les prepared statements d'asyncpg
        "statement_cache_size": 0
    },
)

SessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)

async def get_db():
    async with SessionLocal() as session:
        yield session
