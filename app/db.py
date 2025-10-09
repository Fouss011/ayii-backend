# app/db.py
import os
from fastapi import HTTPException  # <-- ajoute ça
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "").split("?")[0]

engine = create_async_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    connect_args={"ssl": True},
)

SessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)

async def get_db():
    try:
        async with SessionLocal() as session:
            yield session
    except Exception as e:
        # log console + message HTTP clair
        print("[DB] connect error:", repr(e))
        raise HTTPException(status_code=500, detail=f"DB connect error: {e.__class__.__name__}: {e}")
