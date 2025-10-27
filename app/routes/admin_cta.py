# app/routes/admin_cta.py
from __future__ import annotations
import os
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.db import get_db

router = APIRouter(prefix="/cta", tags=["CTA"])

# -------------------------
# Auth très simple par header x-admin-token
# -------------------------
def _admin_token() -> str:
    return (os.getenv("ADMIN_TOKEN") or os.getenv("NEXT_PUBLIC_ADMIN_TOKEN") or "").strip()

async def require_admin(request: Request) -> bool:
    tok = _admin_token()
    if not tok:
        raise HTTPException(status_code=401, detail="admin token not configured")
    hdr = (request.headers.get("x-admin-token") or "").strip()
    if hdr != tok:
        raise HTTPException(status_code=401, detail="invalid admin token")
    return True

@router.get("/ping")
async def cta_ping():
    return {"ok": True}

# -------------------------
# Signature Supabase (optionnelle)
# - si url publique Supabase -> génère une URL signée courte
# - sinon renvoie l'url telle quelle
# -------------------------
async def _supabase_sign_url_if_possible(url: Optional[str], expires_sec: int = 300) -> Optional[str]:
    if not url:
        return url

    supa_url = (os.getenv("SUPABASE_URL") or "").rstrip("/")
    supa_key = os.getenv("SUPABASE_SERVICE_ROLE") or os.getenv("SUPABASE_SERVICE_KEY")
    if not (supa_url and supa_key):
        return url  # pas de signature possible

    marker = "/storage/v1/object/public/"
    if marker not in url:
        return url  # on ne signe que les URLs publiques supabase

    try:
        after = url.split(marker, 1)[1]  # "attachments/xxx/yyy.jpg"
        # POST https://.../storage/v1/object/sign/{after}
        import httpx
        endpoint = f"{supa_url}/storage/v1/object/sign/{after}"
        payload  = {"expiresIn": int(expires_sec)}
        headers  = {"Authorization": f"Bearer {supa_key}", "Content-Type": "application/json", "apikey": supa_key}

        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.post(endpoint, headers=headers, json=payload)
        if r.status_code not in (200, 201):
            return url
        data = r.json()
        signed = data.get("signedURL") or data.get("signedUrl")
        if not signed:
            return url
        # signed est typiquement "/storage/v1/object/sign/attachments/....?token=..."
        if signed.startswith("/"):
            return f"{supa_url}{signed}"
        # au cas où supabase retourne sans slash de tête:
        return f"{supa_url}/storage/v1/{signed}".replace("/storage/v1//", "/storage/v1/")
    except Exception:
        return url


# -------------------------
# Lecture incidents pour CTA
# - On liste des reports "new|confirmed|resolved" (défaut: new)
# - On associe une photo de proximité via attachments (même kind, 48h, 120m)
# -------------------------
DEFAULT_LIMIT = 50

def _sql_incidents(filter_by_status: bool) -> str:
    where_status = "AND r.status = :status" if filter_by_status else ""
    # NOTE: on cible uniquement les reports 'cut' comme événements d'ouverture
    #       Le statut (new/confirmed/resolved) vit dans reports.status
    return f"""
        WITH base AS (
          SELECT
            r.id,
            r.kind::text AS kind,
            r.signal::text AS signal,
            ST_Y((r.geom::geometry)) AS lat,
            ST_X((r.geom::geometry)) AS lng,
            r.created_at,
            COALESCE(r.status,'new') AS status
          FROM reports r
          WHERE LOWER(TRIM(r.signal::text)) = 'cut'
            {where_status}
          ORDER BY r.created_at DESC
          LIMIT :limit
        ),
        with_photo AS (
          SELECT
            b.*,
            (
              SELECT a.url
              FROM attachments a
              WHERE a.kind::text = b.kind
                AND a.created_at > NOW() - INTERVAL '48 hours'
                AND ST_DWithin((a.geom::geography),
                               (ST_SetSRID(ST_MakePoint(b.lng,b.lat),4326)::geography),
                               120)
              ORDER BY a.created_at DESC
              LIMIT 1
            ) AS photo_url
          FROM base b
        )
        SELECT * FROM with_photo
        ORDER BY created_at DESC
    """

@router.get("/incidents")
async def list_incidents(
    ok: bool = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    status: Optional[str] = Query(None, description="Filtrer par 'new'|'confirmed'|'resolved'"),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=500),
):
    params: Dict[str, Any] = {"limit": int(limit)}
    rows = []
    try:
        if status:
            params["status"] = status.strip().lower()
            q = text(_sql_incidents(filter_by_status=True))
        else:
            q = text(_sql_incidents(filter_by_status=False))
        rows = (await db.execute(q, params)).mappings().all()
    except Exception as e:
        # fallback sans status si colonne absente
        try:
            q = text(_sql_incidents(filter_by_status=False))
            rows = (await db.execute(q, {"limit": int(limit)})).mappings().all()
        except Exception as e2:
            raise HTTPException(status_code=500, detail=f"incidents query failed: {e2}")

    now = datetime.now(timezone.utc)
    out: List[Dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        # âge en minutes
        created = d.get("created_at")
        try:
            d["age_min"] = int((now - created).total_seconds() // 60) if created else None
        except Exception:
            d["age_min"] = None
        # URL signée si possible
        d["photo_url"] = await _supabase_sign_url_if_possible(d.get("photo_url"), expires_sec=300)
        out.append(d)

    return {"items": out, "count": len(out)}

# -------------------------
# Changer le statut d'un report
# -------------------------
class MarkStatusIn(BaseModel):
    id: UUID | str
    status: str  # 'new'|'confirmed'|'resolved'

@router.post("/mark_status")
async def mark_status(
    p: MarkStatusIn,
    ok: bool = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    new_status = (p.status or "").strip().lower()
    if new_status not in {"new", "confirmed", "resolved"}:
        raise HTTPException(status_code=400, detail="invalid status")

    # S’assure que la colonne status existe
    try:
        await db.execute(text("ALTER TABLE reports ADD COLUMN IF NOT EXISTS status text"))
        await db.commit()
    except Exception:
        await db.rollback()

    try:
        q = text("""
            UPDATE reports
               SET status = :s
             WHERE id = CAST(:id AS uuid)
         RETURNING id
        """)
        rs = await db.execute(q, {"s": new_status, "id": str(p.id)})
        row = rs.first()
        await db.commit()
        if not row:
            raise HTTPException(status_code=404, detail="report not found")
        return {"ok": True, "id": str(p.id), "status": new_status}
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"mark_status failed: {e}")


# -------------------------
# (Option) Nettoyage ancien — à garder si tu veux
# -------------------------
@router.post("/cleanup")
async def cta_cleanup(
    hours: int = Query(24, ge=1, le=168),
    ok: bool = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Supprime/Archivage simple des reports 'cut' trop anciens de l'affichage CTA.
    Ici on supprime rien dans la DB, à adapter selon ton besoin.
    """
    # Exemple: rien à faire → retourne 0
    return {"deleted": 0}
