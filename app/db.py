# app/db.py
import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

# strip() pour enlever un éventuel \n collé en fin de valeur
DATABASE_URL = os.getenv("DATABASE_URL", "").strip().split("?")[0]

# ⬇️ Pas de connect_args: on laisse asyncpg négocier le TLS comme dans ping-db-deep
engine = create_async_engine(
    DATABASE_URL,                 # postgresql+asyncpg://USER:PASS@HOST:5432/postgres
    pool_pre_ping=True,
)

SessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)

async def get_db():
    async with SessionLocal() as session:
        yield session
