# app/db.py
import os, ssl, certifi
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "").split("?")[0]

# ✅ Construit un contexte TLS qui connaît les autorités racines (certifi)
ssl_ctx = ssl.create_default_context()
ssl_ctx.load_verify_locations(certifi.where())
ssl_ctx.check_hostname = True
ssl_ctx.verify_mode = ssl.CERT_REQUIRED

engine = create_async_engine(
    DATABASE_URL,                 # postgresql+asyncpg://...
    pool_pre_ping=True,
    connect_args={"ssl": ssl_ctx} # ✅ au lieu de {"ssl": True}
)

SessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)

async def get_db():
    async with SessionLocal() as session:
        yield session
