# app/db.py
import os, asyncio
import asyncpg
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool

RAW_URL = os.getenv("DATABASE_URL", "").strip()           # supprime le \n
DATABASE_URL = RAW_URL.split("?")[0]                      # on vire toute query
ASYNC_PG_DSN = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")

async def _asyncpg_connect():
    # Connexion asyncpg **sans prepared statements** (ok pour PgBouncer mode transaction)
    return await asyncpg.connect(
        dsn=ASYNC_PG_DSN,
        statement_cache_size=0,
        prepared_statement_cache_size=0,
        timeout=10.0,
    )

engine = create_async_engine(
    DATABASE_URL,                # ex: postgresql+asyncpg://...:6543/postgres
    poolclass=NullPool,          # ne retient aucune connexion côté app
    pool_pre_ping=True,
    async_creator=_asyncpg_connect,   # 🔑 on impose notre connecteur asyncpg
)

SessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)

async def get_db():
    async with SessionLocal() as session:
        yield session
