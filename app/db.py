# app/db.py — AsyncPG + PgBouncer (6543), no prepared statements, NullPool
import os, asyncpg
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import NullPool

def _clean(url: str) -> str:
    url = (url or "").strip()
    if (url.startswith('"') and url.endswith('"')) or (url.startswith("'") and url.endswith("'")):
        url = url[1:-1]
    return url.replace("\\n","").replace("\n","").replace("\r","").strip()

RAW = _clean(os.getenv("DATABASE_URL", ""))
# 👉 on convertit l'URL en asyncpg, même si Render stocke +psycopg
SQLA_URL = RAW.replace("postgresql+psycopg://", "postgresql+asyncpg://")
ASYNC_PG_DSN = SQLA_URL.replace("postgresql+asyncpg://", "postgresql://")

async def _asyncpg_connect():
    # 🔑 désactive totalement les prepared statements (clé avec PgBouncer transaction)
    return await asyncpg.connect(
        dsn=ASYNC_PG_DSN,
        statement_cache_size=0,
        timeout=10.0,
    )

engine = create_async_engine(
    SQLA_URL,              # postgresql+asyncpg://...:6543/postgres
    poolclass=NullPool,    # ne monopolise pas PgBouncer
    pool_pre_ping=True,
    async_creator=_asyncpg_connect,  # impose notre connecteur
)

SessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)

async def get_db() -> AsyncSession:
    async with SessionLocal() as session:
        yield session
