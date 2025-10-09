# app/db.py  — version locale (sans SSL)
import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from dotenv import load_dotenv

load_dotenv(override=True)

DB_URL = os.getenv("DATABASE_URL", "")
if not DB_URL:
    raise RuntimeError("DATABASE_URL manquant dans .env")

# passe en asyncpg pour SQLAlchemy async
DB_URL_ASYNC = DB_URL.replace("postgresql+psycopg", "postgresql+asyncpg").replace("postgresql://", "postgresql+asyncpg://")

engine = create_async_engine(DB_URL_ASYNC, echo=False, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

async def get_db() -> AsyncSession:
    async with SessionLocal() as session:
        yield session
