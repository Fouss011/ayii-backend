# app/routes/cta.py
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
import os
from app.db import get_db

router = APIRouter(tags=["CTA"])

@router.get("/cta/incidents")
async def cta_incidents(
    request: Request,
    status: str = Query("", description="new|confirmed|resolved (placeholder)"),
    limit: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    # Auth admin
    admin_tok = (os.getenv("ADMIN_TOKEN") or "").strip()
    req_tok   = (request.headers.get("x-admin-token") or "").strip()
    if admin_tok and req_tok != admin_tok:
        raise HTTPException(status_code=401, detail="invalid admin token")

    # NB: on renvoie bien phone + une photo/vidéo récente si dispo
    q = text("""
        WITH latest_att AS (
          SELECT DISTINCT ON (kind, round(CAST(ST_Y(geom::geometry) AS numeric), 5), round(CAST(ST_X(geom::geometry) AS numeric), 5))
                 kind,
                 round(CAST(ST_Y(geom::geometry) AS numeric), 5) AS lat_r,
                 round(CAST(ST_X(geom::geometry) AS numeric), 5) AS lng_r,
                 url,
                 mime_type,
                 created_at
          FROM attachments
          WHERE created_at > NOW() - INTERVAL '72 hours'
          ORDER BY kind, lat_r, lng_r, created_at DESC
        )
        SELECT
          r.id,
          r.kind::text   AS kind,
          r.signal::text AS signal,
          ST_Y(r.geom::geometry) AS lat,
          ST_X(r.geom::geometry) AS lng,
          r.created_at,
          r.phone, -- 👈 IMPORTANT
          'new'::text AS status,
          la.url       AS photo_url,
          EXTRACT(EPOCH FROM (NOW() - r.created_at))::int / 60 AS age_min
        FROM reports r
        LEFT JOIN latest_att la
          ON la.kind = r.kind::text
         AND round(CAST(ST_Y(r.geom::geometry) AS numeric), 5) = la.lat_r
         AND round(CAST(ST_X(r.geom::geometry) AS numeric), 5) = la.lng_r
        WHERE LOWER(TRIM(r.signal::text)) = 'cut'
        ORDER BY r.created_at DESC
        LIMIT :lim
    """)
    res = await db.execute(q, {"lim": limit})

    items = []
    for r in res.fetchall():
        items.append({
            "id": r.id,
            "kind": r.kind,
            "signal": r.signal,
            "lat": float(r.lat),
            "lng": float(r.lng),
            "created_at": r.created_at,
            "status": r.status,
            "photo_url": r.photo_url,
            "age_min": int(r.age_min) if r.age_min is not None else None,
            "phone": getattr(r, "phone", None),  # 👈 renvoyé au JSON
        })
    return {"items": items, "count": len(items)}
