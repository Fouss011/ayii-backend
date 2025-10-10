# psycopg async + PgBouncer (6543) — no prepared statements
import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import NullPool

def _clean(url: str) -> str:
    url = (url or "").strip()
    if (url.startswith('"') and url.endswith('"')) or (url.startswith("'") and url.endswith("'")):
        url = url[1:-1]
    # au cas où un \n traîne
    return url.replace("\\n","").replace("\n","").replace("\r","").strip().split("?")[0]

DATABASE_URL = _clean(os.getenv("DATABASE_URL", ""))  # <- doit être en psycopg dans Render

engine = create_async_engine(
    DATABASE_URL,             # ex: postgresql+psycopg://...:6543/postgres
    poolclass=NullPool,       # ne monopolise pas PgBouncer
    pool_pre_ping=True,
    connect_args={
        "prepare_threshold": 0  # 🔑 pas de prepared statements côté psycopg
    },
)

SessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)

async def get_db() -> AsyncSession:
    async with SessionLocal() as session:
        yield session
