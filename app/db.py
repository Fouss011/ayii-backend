# app/db.py
import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool

# Récup DSN tel quel (sans \n ni quotes)
raw = os.getenv("DATABASE_URL", "").strip()

# ⚠️ Force psycopg (pas asyncpg), sinon on retombe sur l'erreur pgbouncer
# Si jamais quelqu’un met 'postgresql+asyncpg', on remplace par psycopg.
DATABASE_URL = raw.replace("postgresql+asyncpg://", "postgresql+psycopg://")

# Avec PgBouncer (pool_mode=transaction), on évite le pool côté app
# + on désactive les prepared statements côté psycopg (prepare_threshold=None)
engine = create_async_engine(
    DATABASE_URL,
    poolclass=NullPool,        # pas de pool SQLAlchemy (laisse PgBouncer gérer)
    pool_pre_ping=True,
    connect_args={
        "sslmode": "require",       # Supabase pooler requiert SSL
        "prepare_threshold": None,  # désactive les prepared statements (psycopg v3)
    },
)

SessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)

async def get_db():
    async with SessionLocal() as session:
        yield session
