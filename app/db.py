# app/db.py
import os
import asyncpg
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import NullPool

RAW_URL = os.getenv("DATABASE_URL", "").strip()           # supprime \n collés
DATABASE_URL = RAW_URL.split("?")[0]                      # on vire toute query
ASYNC_PG_DSN = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")

async def _asyncpg_connect():
    # 👉 connexion asyncpg compatible PgBouncer (transaction): PAS de prepared statements
    return await asyncpg.connect(
        dsn=ASYNC_PG_DSN,
        statement_cache_size=0,
        prepared_statement_cache_size=0,
        timeout=10.0,
    )

engine = create_async_engine(
    DATABASE_URL,                 # postgresql+asyncpg://...:6543/postgres
    poolclass=NullPool,           # ne monopolise pas le pool
    pool_pre_ping=True,
    async_creator=_asyncpg_connect,  # 🔑 on impose notre connecteur
)

SessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)

async def get_db() -> AsyncSession:
    async with SessionLocal() as session:
        yield session
