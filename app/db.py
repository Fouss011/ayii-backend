# app/db.py — Direct Supabase (5432), SSL + IPv4 forcé
import os, ssl, certifi, socket, asyncpg
from urllib.parse import urlparse
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import NullPool

RAW_URL = os.getenv("DATABASE_URL", "").strip()
DATABASE_URL = RAW_URL.split("?")[0]
parsed = urlparse(DATABASE_URL.replace("postgresql+asyncpg://","postgresql://"))

USER = parsed.username
PASS = parsed.password
HOST = parsed.hostname         # db.<project>.supabase.co
PORT = parsed.port or 5432
DB   = parsed.path.lstrip("/") or "postgres"

# Résolution IPv4 (A record)
def resolve_ipv4(host, port):
    for fam,_,_,_,sockaddr in socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM):
        return sockaddr[0]
    return host  # fallback (laisser asyncpg gérer)

IPV4 = resolve_ipv4(HOST, PORT)

ssl_ctx = ssl.create_default_context()
ssl_ctx.load_verify_locations(certifi.where())
ssl_ctx.check_hostname = True
ssl_ctx.verify_mode = ssl.CERT_REQUIRED

async def _asyncpg_connect():
    return await asyncpg.connect(
        host=IPV4,                 # 🔒 IPv4
        port=PORT,
        user=USER,
        password=PASS,
        database=DB,
        ssl=ssl_ctx,
        timeout=10.0,
    )

engine = create_async_engine(
    DATABASE_URL,
    poolclass=NullPool,
    pool_pre_ping=True,
    async_creator=_asyncpg_connect,   # 🔑 impose notre connecteur (IPv4 + SSL)
)

SessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False)

async def get_db() -> AsyncSession:
    async with SessionLocal() as session:
        yield session
