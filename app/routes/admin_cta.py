# app/routes/admin_cta.py
import os
from fastapi import APIRouter, Depends, HTTPException, Header, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from typing import Optional

# Import tolérant de get_db
try:
    from app.dependencies import get_db
except Exception:
    try:
        from app.db import get_db
    except Exception as e:
        raise RuntimeError("Impossible d'importer get_db (ni app.dependencies.get_db, ni app.db.get_db).") from e

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
    # On essaie d'abord avec les colonnes Phase 1 ; si ça casse, on retombe sur un SELECT minimal
    base_where = "WHERE 1=1"
    params = {"limit": limit}
    if status:
        base_where += " AND status = :status"
        params["status"] = status

    q_full = text(f"""
        SELECT id, kind, signal, lat, lng, created_at, status, photo_url
        FROM reports
        {base_where}
        ORDER BY created_at DESC
        LIMIT :limit
    """)

    try:
        rows = (await db.execute(q_full, params)).mappings().all()
    except Exception as e:
        # fallback si colonnes manquantes (migration non appliquée)
        q_min = text(f"""
            SELECT id, kind, signal, lat, lng, created_at
            FROM reports
            {"WHERE 1=1" if not status else "WHERE 1=1"}   -- status ignoré
            ORDER BY created_at DESC
            LIMIT :limit
        """)
        rows = (await db.execute(q_min, {"limit": limit})).mappings().all()

    # âge en minutes
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    out = []
    for r in rows:
        d = dict(r)
        created = d.get("created_at")
        try:
            age_min = int((now - created).total_seconds() // 60) if created else None
        except Exception:
            age_min = None
        d.setdefault("status", "new")
        d.setdefault("photo_url", None)
        d["age_min"] = age_min
        out.append(d)
    return {"items": out, "count": len(out)}

@router.post("/cleanup")
async def do_cleanup(
    ok: bool = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    hours: int = 24
):
    try:
        from app.services.cleanup import cleanup_old_reports
        n = await cleanup_old_reports(db, hours=hours)
        return {"deleted": n}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"cleanup error: {e}")
