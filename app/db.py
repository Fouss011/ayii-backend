# app/db.py  — Connexion directe Supabase (sans PgBouncer)
import os, ssl, certifi
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import NullPool

# Nettoie la valeur (retire espaces/retours & query)
DATABASE_URL = os.getenv("DATABASE_URL", "").strip().split("?")[0]
# Exemple attendu :
# postgresql+asyncpg://postgres:Temya2025Secure@db.sdrczqseuhevmcjmjtep.supabase.co:5432/postgres

# SSL strict requis par Supabase direct
ssl_ctx = ssl.create_default_context()
ssl_ctx.load_verify_locations(certifi.where())
ssl_ctx.check_hostname = True
ssl_ctx.verify_mode = ssl.CERT_REQUIRED

engine = create_async_engine(
    DATABASE_URL,
    poolclass=NullPool,          # évite de retenir des connexions côté app
    pool_pre_ping=True,
    connect_args={"ssl": ssl_ctx}  # ✅ IMPORTANT: TLS vérifié
)

SessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)

async def get_db() -> AsyncSession:
    async with SessionLocal() as session:
        yield session
