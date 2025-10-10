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

# --- /dev/env-db : affiche la valeur (sécurisée) de DATABASE_URL ---
from fastapi.responses import JSONResponse
from app.db import engine
from sqlalchemy import text
import os

@router.get("/env-db")
async def env_db():
    dsn = os.getenv("DATABASE_URL", "")
    safe = dsn
    try:
        if "://" in dsn and "@" in dsn:
            proto, rest = dsn.split("://", 1)
            safe = proto + "://" + rest.split("@")[-1]
    except Exception:
        pass
    return {
        "DATABASE_URL_safe": safe,
        "has_ssl_query": ("?sslmode=" in dsn.lower()),
        "driver_hint": ("+asyncpg" in dsn),
    }

# --- /dev/ping-db-safe : test via SQLAlchemy/engine, message JSON clair ---
@router.get("/ping-db-safe")
async def ping_db_safe():
    from fastapi.responses import JSONResponse
    from sqlalchemy import text
    from app.db import engine
    try:
        async with engine.begin() as conn:
            val = await conn.scalar(text("SELECT 1"))
        return {"ok": True, "db_ok": bool(val == 1)}
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"ok": False, "where": "sqlalchemy/connect", "error": f"{type(e).__name__}: {e}"}
        )



