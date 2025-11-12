# app/routes/cta.py
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
import os
from app.db import get_db

router = APIRouter(prefix="/cta", tags=["CTA"])

def _auth_admin(request: Request):
    admin_tok = (os.getenv("ADMIN_TOKEN") or "").strip()
    req_tok   = (request.headers.get("x-admin-token") or "").strip()
    if admin_tok and req_tok != admin_tok:
        raise HTTPException(status_code=401, detail="invalid admin token")

_SQL_DIST = """
SELECT
  r.id,
  r.kind::text   AS kind,
  r.signal::text AS signal,
  ST_Y(r.geom::geometry) AS lat,
  ST_X(r.geom::geometry) AS lng,
  r.created_at,
  COALESCE(r.status,'new') AS status,
  r.phone::text AS phone,  -- ✅ alias explicite
  (
    SELECT a.public_url
    FROM attachments a
    WHERE a.kind = r.kind::text
      AND ST_DWithin(a.geom::geography, r.geom::geography, 150)
      AND a.created_at BETWEEN r.created_at - INTERVAL '72 hours' AND NOW()
    ORDER BY a.created_at DESC
    LIMIT 1
  ) AS photo_url,
  (
    SELECT a.mime_type
    FROM attachments a
    WHERE a.kind = r.kind::text
      AND ST_DWithin(a.geom::geography, r.geom::geography, 150)
      AND a.created_at BETWEEN r.created_at - INTERVAL '72 hours' AND NOW()
    ORDER BY a.created_at DESC
    LIMIT 1
  ) AS attachment_mime,
  (
    SELECT CASE
             WHEN a.mime_type ILIKE 'video/%%' THEN true
             WHEN a.public_url ~* '\\.(mp4|webm|mov)$' THEN true
             ELSE false
           END
    FROM attachments a
    WHERE a.kind = r.kind::text
      AND ST_DWithin(a.geom::geography, r.geom::geography, 150)
      AND a.created_at BETWEEN r.created_at - INTERVAL '72 hours' AND NOW()
    ORDER BY a.created_at DESC
    LIMIT 1
  ) AS is_video,
  EXTRACT(EPOCH FROM (NOW() - r.created_at))::int / 60 AS age_min
FROM reports r
WHERE LOWER(TRIM(r.signal::text)) = 'cut'
{where_status}
ORDER BY r.created_at DESC
LIMIT :lim
"""


def _build_sql(status: str):
    if (status or "").strip().lower() in {"new","confirmed","resolved"}:
        return _SQL_DIST.format(where_status="AND COALESCE(r.status,'new') = :status")
    return _SQL_DIST.format(where_status="")

async def _run(request: Request, status: str, limit: int, db: AsyncSession):
    _auth_admin(request)
    sql = text(_build_sql(status))
    params = {"lim": int(limit)}
    if (status or "").strip().lower() in {"new","confirmed","resolved"}:
        params["status"] = status.strip().lower()

    res = await db.execute(sql, params)
    rows = res.fetchall()
    items = []
    for row in rows:
        m = row._mapping
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

@router.get("/incidents_v2")
async def cta_incidents_v2(
    request: Request,
    status: str = Query("", description="new|confirmed|resolved"),
    limit: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    out = await _run(request, status, limit, db)
    return {"api_version": "v2", **out}

@router.get("/incidents")
async def cta_incidents(
    request: Request,
    status: str = Query("", description="new|confirmed|resolved"),
    limit: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    # alias (peut être supprimé plus tard)
    return await _run(request, status, limit, db)
