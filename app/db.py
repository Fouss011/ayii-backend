# app/db.py — AsyncPG + PgBouncer (6543), no prepared statements, NullPool
import os, asyncpg
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import NullPool

def _clean(url: str) -> str:
    url = (url or "").strip()
    if (url.startswith('"') and url.endswith('"')) or (url.startswith("'") and url.endswith("'")):
        url = url[1:-1]
    url = url.replace("\\n", "").replace("\n", "").replace("\r", "").strip()
    return url

RAW = _clean(os.getenv("DATABASE_URL", ""))
# 👉 peu importe ce que Render contient (psycopg/asyncpg), on impose asyncpg pour SQLAlchemy :
SQLA_URL = RAW.replace("postgresql+psycopg://", "postgresql+asyncpg://")
ASYNC_PG_DSN = SQLA_URL.replace("postgresql+asyncpg://", "postgresql://")

async def _asyncpg_connect():
    # 🔑 désactive le cache de prepared statements (clé pour PgBouncer transaction)
    return await asyncpg.connect(
        dsn=ASYNC_PG_DSN,
        statement_cache_size=0,
        timeout=10.0,
    )

engine = create_async_engine(
    SQLA_URL,              # postgresql+asyncpg://...:6543/postgres
    poolclass=NullPool,    # on ne garde pas de connexions côté app
    pool_pre_ping=True,
    async_creator=_asyncpg_connect,  # on impose notre connecteur
)

SessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)

async def get_db() -> AsyncSession:
    async with SessionLocal() as session:
        yield session
