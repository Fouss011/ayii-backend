# app/routes/dev.py
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.db import get_db
from app.services.aggregation import run_aggregation

router = APIRouter(prefix="/dev", tags=["dev"])

@router.get("/ping-db")
async def ping_db(db: AsyncSession = Depends(get_db)):
    r = await db.execute(text("SELECT 1"))
    return {"db_ok": bool(r.scalar_one() == 1)}

@router.post("/aggregate")
async def dev_aggregate(db: AsyncSession = Depends(get_db)):
    try:
        await run_aggregation(db)
        return {"ok": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/seed")
async def dev_seed(db: AsyncSession = Depends(get_db)):
    try:
        await db.execute(text("""
            INSERT INTO outages (kind, status, center, radius_m, started_at)
            VALUES ('power','ongoing', ST_SetSRID(ST_MakePoint(1.21, 6.17),4326)::geography, 600, NOW())
            ON CONFLICT DO NOTHING;
        """))
        await db.execute(text("""
            INSERT INTO reports (kind, signal, geom, user_id)
            VALUES ('power','cut', ST_SetSRID(ST_MakePoint(1.2105, 6.1705),4326)::geography, 'seed_user');
        """))
        await db.commit()
        return {"ok": True}
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/reset_user")
async def dev_reset_user(payload: dict = Body(...), db: AsyncSession = Depends(get_db)):
    uid = (payload or {}).get("user_id")
    if not uid:
        raise HTTPException(status_code=400, detail="user_id requis")
    try:
        await db.execute(text("DELETE FROM reports WHERE user_id = :uid"), {"uid": uid})
        await run_aggregation(db)
        await db.commit()
        return {"ok": True}
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    
    # --- Ping DB approfondi (diagnostic) ---
import os, socket, asyncio, asyncpg  # ⬅️ ajoutes ces imports en haut si besoin

@router.get("/ping-db-deep")
async def ping_db_deep():
    dsn = os.getenv("DATABASE_URL", "")
    # masque user:pass (pour retour JSON safe)
    safe_dsn = dsn
    try:
        if "://" in dsn and "@" in dsn:
            proto, rest = dsn.split("://",1)
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
            resolved.append({"family":"IPv6" if fam==socket.AF_INET6 else "IPv4", "addr": sockaddr[0]})
    except Exception as e:
        dns_err = f"getaddrinfo: {e.__class__.__name__}: {e}"

    # TCP connect rapide (essaye IPv4 d’abord)
    connect_ok, connect_err = False, None
    try:
        ip = next((r["addr"] for r in resolved if r["family"]=="IPv4"), resolved[0]["addr"])
        reader, writer = await asyncio.wait_for(asyncio.open_connection(ip, 5432), timeout=3.0)
        writer.close(); await writer.wait_closed()
        connect_ok = True
    except Exception as e:
        connect_err = f"tcp_connect: {e.__class__.__name__}: {e}"

    # asyncpg SELECT 1 (convertit le DSN en postgresql://…)
    apg_ok, apg_err = False, None
    try:
        apg_dsn = dsn.replace("postgresql+asyncpg://","postgresql://").replace("postgresql+psycopg://","postgresql://")
        conn = await asyncpg.connect(dsn=apg_dsn, timeout=5.0)  # sslmode=require doit déjà être dans le DSN
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
        "asyncpg_error": apg_err
    }

