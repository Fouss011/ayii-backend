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
