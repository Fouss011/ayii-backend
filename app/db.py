# app/db.py
import os, ssl
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "").split("?")[0]

# ✅ Contexte TLS par défaut (mêmes CA que le système, comme ton test asyncpg OK)
ssl_ctx = ssl.create_default_context()   # NE PAS charger certifi ici

engine = create_async_engine(
    DATABASE_URL,                       # postgresql+asyncpg://...
    pool_pre_ping=True,
    connect_args={"ssl": ssl_ctx},      # <- passer le SSLContext (pas True/False)
)

SessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)

async def get_db():
    async with SessionLocal() as session:
        yield session
