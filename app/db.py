# app/db.py
import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.pool import NullPool

# retire espaces/retours éventuels et toute query (?...)
DATABASE_URL = os.getenv("DATABASE_URL", "").strip().split("?")[0]

engine = create_async_engine(
    DATABASE_URL,
    poolclass=NullPool,      # évite de monopoliser PgBouncer (transaction mode)
    pool_pre_ping=True,
    connect_args={
        # 🔑 clé pour PgBouncer en mode "transaction"
        # Certaines versions d'asyncpg/sqlalchemy prennent l'un ou l'autre nom.
        "statement_cache_size": 0,
        "prepared_statement_cache_size": 0,  # on met les deux pour être certains
    },
)

SessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)

async def get_db():
    async with SessionLocal() as session:
        yield session
