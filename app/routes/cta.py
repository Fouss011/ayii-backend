# app/routes/cta.py
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
import os
from app.db import get_db

# Router CTA (prefix = /cta)
router = APIRouter(prefix="/cta", tags=["CTA"])

def _auth_admin(request: Request):
    admin_tok = (os.getenv("ADMIN_TOKEN") or "").strip()
    req_tok   = (request.headers.get("x-admin-token") or "").strip()
    if admin_tok and req_tok != admin_tok:
        raise HTTPException(status_code=401, detail="invalid admin token")

_SQL_WITH_MEDIA = """
WITH att AS (
  SELECT
    kind::text AS kind,
    ROUND(CAST(ST_Y(geom::geometry) AS numeric), 5) AS lat_r,
    ROUND(CAST(ST_X(geom::geometry) AS numeric), 5) AS lng_r,
    public_url,
    created_at
  FROM attachments
  WHERE created_at > NOW() - INTERVAL '72 hours'
)
SELECT
  r.id,
  r.kind::text   AS kind,
  r.signal::text AS signal,
  ST_Y(r.geom::geometry) AS lat,
  ST_X(r.geom::geometry) AS lng,
  r.created_at,
  COALESCE(r.status,'new') AS status,
  r.phone,
  (
    SELECT a.public_url
    FROM att a
    WHERE a.kind = r.kind::text
      AND ROUND(CAST(ST_Y(r.geom::geometry) AS numeric), 5) = a.lat_r
      AND ROUND(CAST(ST_X(r.geom::geometry) AS numeric), 5) = a.lng_r
    ORDER BY a.created_at DESC
    LIMIT 1
  ) AS photo_url,
  EXTRACT(EPOCH FROM (NOW() - r.created_at))::int / 60 AS age_min
FROM reports r
WHERE LOWER(TRIM(r.signal::text)) = 'cut'
{where_status}
ORDER BY r.created_at DESC
LIMIT :lim
"""

async def _run_incidents(
    request: Request,
    status: str,
    limit: int,
    db: AsyncSession,
):
    _auth_admin(request)

    status_norm = (status or "").strip().lower()
    if status_norm in {"new", "confirmed", "resolved"}:
        where_status = "AND COALESCE(r.status,'new') = :status"
    else:
        where_status = ""

    sql = text(_SQL_WITH_MEDIA.format(where_status=where_status))
    params = {"lim": int(limit)}
    if where_status:
        params["status"] = status_norm

    res = await db.execute(sql, params)
    rows = res.fetchall()

    items = []
    for r in rows:
        m = r._mapping
        items.append({
            "id": m["id"],
            "kind": m["kind"],
            "signal": m["signal"],
            "lat": float(m["lat"]),
            "lng": float(m["lng"]),
            "created_at": m["created_at"],
            "status": m["status"],
            "photo_url": m["photo_url"],   # ✅ image OU vidéo
            "age_min": int(m["age_min"]) if m["age_min"] is not None else None,
            "phone": m.get("phone"),       # ✅ téléphone
        })
    return items

# -----------------------------
# Route principale V2
# -----------------------------
@router.get("/incidents_v2")
async def cta_incidents_v2(
    request: Request,
    status: str = Query("", description="new|confirmed|resolved"),
    limit: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    items = await _run_incidents(request, status, limit, db)
    return {"api_version": "v2", "items": items, "count": len(items)}

# -----------------------------
# Alias historique /cta/incidents
# -----------------------------
@router.get("/incidents")
async def cta_incidents(
    request: Request,
    status: str = Query("", description="new|confirmed|resolved"),
    limit: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    items = await _run_incidents(request, status, limit, db)
    return {"items": items, "count": len(items)}
