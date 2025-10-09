# app/routes/dev.py
import os, socket, asyncio, asyncpg
from fastapi import APIRouter
from sqlalchemy import text

router = APIRouter(prefix="/dev", tags=["dev"])

@router.get("/ping-db-deep")
async def ping_db_deep():
    dsn = os.getenv("DATABASE_URL", "")
    # masque user:pass
    safe_dsn = dsn
    try:
        if "://" in dsn and "@" in dsn:
            proto, rest = dsn.split("://", 1)
            safe_dsn = proto + "://" + rest.split("@")[-1]
    except Exception:
        pass

    # Host du DSN
    try:
        host = dsn.split("@")[1].split(":")[0]
    except Exception:
        host = None

    # DNS → IPs
    resolved, dns_err = [], None
    try:
        for fam, _, _, _, sockaddr in socket.getaddrinfo(host, 5432, 0, socket.SOCK_STREAM):
            resolved.append({"family": "IPv6" if fam==socket.AF_INET6 else "IPv4", "addr": sockaddr[0]})
    except Exception as e:
        dns_err = f"getaddrinfo: {e.__class__.__name__}: {e}"

    # TCP connect rapide (IPv4 d’abord si dispo)
    connect_ok, connect_err = False, None
    try:
        ip = next((r["addr"] for r in resolved if r["family"]=="IPv4"), (resolved[0]["addr"] if resolved else None))
        if ip:
            reader, writer = await asyncio.wait_for(asyncio.open_connection(ip, 5432), timeout=3.0)
            writer.close(); await writer.wait_closed()
            connect_ok = True
    except Exception as e:
        connect_err = f"tcp_connect: {e.__class__.__name__}: {e}"

    # asyncpg SELECT 1 (désactive le statement cache pour PgBouncer transaction)
    apg_ok, apg_err = False, None
    try:
        apg_dsn = dsn.replace("postgresql+asyncpg://","postgresql://").replace("postgresql+psycopg://","postgresql://")
        conn = await asyncpg.connect(
            dsn=apg_dsn,
            timeout=5.0,
            statement_cache_size=0,  # 🔑 clé pour pooler en mode transaction
        )
        val = await conn.fetchval("SELECT 1")
        apg_ok = (val == 1)
        await conn.close()
    except Exception as e:
        apg_err = f"asyncpg: {e.__class__.__name__}: {e}"

    return {
        "dsn": safe_dsn,
        "host": host,
        "resolved": resolved,
        "dns_error": dns_err,
        "connect_ok": connect_ok,
        "connect_error": connect_err,
        "asyncpg_ok": apg_ok,
        "asyncpg_error": apg_err,
    }
