# app/routes/admin_cta.py
import os
from fastapi import APIRouter, Depends, HTTPException, Header, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from typing import Optional

# Ton projet doit exposer get_db (déjà présent chez toi)
try:
    from app.dependencies import get_db
except Exception as e:
    raise RuntimeError("Besoin de app.dependencies.get_db") from e

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN") or "change-me"

router = APIRouter(prefix="/cta", tags=["cta"])

def require_admin(token: Optional[str] = Header(None, alias="x-admin-token")):
    if not token or token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return True

@router.get("/incidents")
async def list_incidents(
    ok: bool = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    status: Optional[str] = Query(None),
    limit: int = Query(100, le=500)
):
    where = "WHERE 1=1"
    params = {}
    if status:
        where += " AND status = :status"
        params["status"] = status
    q = text(f"""
        SELECT id, kind, signal, lat, lng, created_at, status, photo_url
        FROM reports
        {where}
        ORDER BY created_at DESC
        LIMIT :limit
    """)
    params["limit"] = limit
    rows = (await db.execute(q, params)).mappings().all()

    # âge en minutes (pour affichage "il y a X min")
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    out = []
    for r in rows:
        created = r.get("created_at")
        age_min = int((now - created).total_seconds() // 60) if created else None
        out.append({**dict(r), "age_min": age_min})
    return {"items": out, "count": len(out)}

@router.post("/cleanup")
async def do_cleanup(
    ok: bool = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    hours: int = 24
):
    from app.services.cleanup import cleanup_old_reports
    n = await cleanup_old_reports(db, hours=hours)
    return {"deleted": n}
