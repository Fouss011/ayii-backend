# app/routes/admin_cta.py
import os
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Header, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

# ✅ Import tolérant de get_db
try:
    from app.dependencies import get_db  # si présent
except Exception:
    try:
        from app.db import get_db        # fallback (cas courant chez toi)
    except Exception as e:
        raise RuntimeError("Impossible d'importer get_db (ni app.dependencies.get_db, ni app.db.get_db).") from e

ADMIN_TOKEN = (os.getenv("ADMIN_TOKEN") or os.getenv("NEXT_PUBLIC_ADMIN_TOKEN") or "").strip()
ATTACH_WINDOW_H = int(os.getenv("ATTACH_WINDOW_H", "48"))     # fenêtre temporelle des attachments
ATTACH_RADIUS_M = int(os.getenv("ATTACH_RADIUS_M", "120"))    # rayon de recherche autour d'un report
DEFAULT_LIMIT   = 100

router = APIRouter(prefix="/cta", tags=["cta"])


# ---------------------------------------------------------------------
# Auth très simple via x-admin-token
# ---------------------------------------------------------------------
def require_admin(token: Optional[str] = Header(None, alias="x-admin-token")) -> bool:
    if not ADMIN_TOKEN or not token or token.strip() != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return True


# ---------------------------------------------------------------------
# Helper SQL : build SELECT avec join LATERAL => photo_url depuis attachments
# ---------------------------------------------------------------------
def _build_query_with_attachment(filter_by_status: bool) -> str:
    """
    Si filter_by_status=True, inclut "AND r.status = :status" dans WHERE.
    Retourne un SELECT qui expose lat/lng, status, created_at, et la dernière photo proche.
    """
    where_status = "AND r.status = :status" if filter_by_status else ""
    q = f"""
        SELECT
            r.id,
            r.kind::text     AS kind,
            r.signal::text   AS signal,
            ST_Y(r.geom::geometry) AS lat,
            ST_X(r.geom::geometry) AS lng,
            r.created_at,
            r.status,
            att.url          AS photo_url
        FROM reports r
        LEFT JOIN LATERAL (
            SELECT a.url
            FROM attachments a
            WHERE a.kind::text = r.kind::text
              AND a.created_at > NOW() - INTERVAL '{ATTACH_WINDOW_H} hours'
              AND ST_DWithin(a.geom::geography, r.geom::geography, {ATTACH_RADIUS_M})
            ORDER BY a.created_at DESC
            LIMIT 1
        ) att ON TRUE
        WHERE 1=1
        {where_status}
        ORDER BY r.created_at DESC
        LIMIT :limit
    """
    return q


# ---------------------------------------------------------------------
# GET /cta/incidents
# Liste les reports avec dernière photo proche (si existante)
# ---------------------------------------------------------------------
@router.get("/incidents")
async def list_incidents(
    ok: bool = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    status: Optional[str] = Query(None, description="Filtrer par status 'new'|'confirmed'|'resolved'"),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=500),
):
    # Tente une version avec filtre status si fourni; si erreur (colonne manquante),
    # retombe sur une version sans filtre.
    params: Dict[str, Any] = {"limit": int(limit)}
    try:
        if status:
            params["status"] = status
            q = text(_build_query_with_attachment(filter_by_status=True))
        else:
            q = text(_build_query_with_attachment(filter_by_status=False))

        rows = (await db.execute(q, params)).mappings().all()
    except Exception:
        # fallback (au cas où status n'existe pas, ou autre souci)
        q = text(_build_query_with_attachment(filter_by_status=False))
        rows = (await db.execute(q, {"limit": int(limit)})).mappings().all()

    # âge en minutes
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)

    out: List[Dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        created = d.get("created_at")
        try:
            age_min = int((now - created).total_seconds() // 60) if created else None
        except Exception:
            age_min = None
        d["age_min"] = age_min
        out.append(d)

    return {"items": out, "count": len(out)}


# ---------------------------------------------------------------------
# POST /cta/cleanup
# Nettoyage de vieux reports (utilise ton service si présent)
# ---------------------------------------------------------------------
@router.post("/cleanup")
async def do_cleanup(
    ok: bool = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    hours: int = Query(24, ge=1, le=24*31, description="Supprimer/archiver les reports plus vieux que N heures"),
):
    """
    Appelle app.services.cleanup.cleanup_old_reports si dispo.
    Sinon, fallback : suppression basique en SQL.
    """
    try:
        try:
            from app.services.cleanup import cleanup_old_reports
            n = await cleanup_old_reports(db, hours=hours)
            return {"deleted": n}
        except Exception:
            # Fallback : delete simple si le service n'existe pas
            q = text("DELETE FROM reports WHERE created_at < NOW() - (:h || ' hours')::interval")
            res = await db.execute(q, {"h": int(hours)})
            await db.commit()
            # rowcount peut être None selon driver; on renvoie au moins ok=true
            return {"ok": True, "deleted": getattr(res, "rowcount", None)}
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"cleanup error: {e}")
