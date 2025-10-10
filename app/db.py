# app/db.py  — Pooler 6543 (PgBouncer, mode transaction)
import os, asyncpg
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import NullPool

RAW_URL = os.getenv("DATABASE_URL", "").strip()          # supprime espaces/retours
DATABASE_URL = RAW_URL.split("?")[0]                     # retire toute query
ASYNC_PG_DSN = DATABASE_URL.replace("postgresql+asyncpg://","postgresql://")

async def _asyncpg_connect():
    return await asyncpg.connect(
        dsn=ASYNC_PG_DSN,
        statement_cache_size=0,            # 🔑 indispensable avec PgBouncer (transaction)
        prepared_statement_cache_size=0,   # 🔑 idem
        timeout=10.0,
    )

engine = create_async_engine(
    DATABASE_URL,
    poolclass=NullPool,     # ne monopolise pas le pooler
    pool_pre_ping=True,
    async_creator=_asyncpg_connect,  # 🔑 impose notre connecteur
)

SessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)

async def get_db() -> AsyncSession:
    async with SessionLocal() as session:
        yield session
