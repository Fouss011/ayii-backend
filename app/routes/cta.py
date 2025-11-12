# app/routes/cta.py
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
import os
from app.db import get_db

# ✅ définir le router AVANT les décorateurs
router = APIRouter(prefix="/cta", tags=["CTA"])

def _auth_admin(request: Request):
    admin_tok = (os.getenv("ADMIN_TOKEN") or "").strip()
    req_tok   = (request.headers.get("x-admin-token") or "").strip()
    if admin_tok and req_tok != admin_tok:
        raise HTTPException(status_code=401, detail="invalid admin token")

_SQL_BASE = """
WITH att AS (
  SELECT
    kind::text AS kind,
    round(CAST(ST_Y(geom::geometry) AS numeric), 5) AS lat_r,
    round(CAST(ST_X(geom::geometry) AS numeric), 5) AS lng_r,
    public_url,               -- ✅ colonne correcte
    mime_type,
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
  r.phone,                 -- ✅ on renvoie le téléphone
  (
    SELECT a.public_url
    FROM att a
    WHERE a.kind = r.kind::text
      AND round(CAST(ST_Y(r.geom::geometry) AS numeric), 5) = a.lat_r
      AND round(CAST(ST_X(r.geom::geometry) AS numeric), 5) = a.lng_r
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

def _build_sql(status: str):
    if (status or "").strip().lower() in {"new","confirmed","resolved"}:
        return _SQL_BASE.format(where_status="AND COALESCE(r.status,'new') = :status")
    return _SQL_BASE.format(where_status="")

async def _run_incidents(request: Request, status: str, limit: int, db: AsyncSession):
    _auth_admin(request)
    sql = text(_build_sql(status))
    params = {"lim": int(limit)}
    if (status or "").strip().lower() in {"new","confirmed","resolved"}:
        params["status"] = status.strip().lower()
    res = await db.execute(sql, params)
    rows = res.fetchall()
    items = []
    for r in rows:
        m = getattr(r, "_mapping", r)
        items.append({
            "id": m["id"],
            "kind": m["kind"],
            "signal": m["signal"],
            "lat": float(m["lat"]),
            "lng": float(m["lng"]),
            "created_at": m["created_at"],
            "status": m["status"],
            "photo_url": m["photo_url"],
            "age_min": int(m["age_min"]) if m["age_min"] is not None else None,
            "phone": m.get("phone"),
        })
    return {"items": items, "count": len(items)}

@router.get("/incidents")
async def cta_incidents(
    request: Request,
    status: str = Query("", description="new|confirmed|resolved"),
    limit: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    return await _run_incidents(request, status, limit, db)

@router.get("/incidents_v2")
async def cta_incidents_v2(
    request: Request,
    status: str = Query("", description="new|confirmed|resolved"),
    limit: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    # même logique que /incidents, on garde V2 pour tester/casser le cache
    out = await _run_incidents(request, status, limit, db)
    return {"api_version": "v2", **out}
