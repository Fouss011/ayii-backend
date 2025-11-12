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
    status: str = Query("", description="new|confirmed|resolved (pas encore filtré)"),
    limit: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    # vérif token admin
    admin_tok = (os.getenv("ADMIN_TOKEN") or "").strip()
    req_tok   = (request.headers.get("x-admin-token") or "").strip()
    if admin_tok and req_tok != admin_tok:
        raise HTTPException(status_code=401, detail="invalid admin token")

    # IMPORTANT: on renvoie bien phone
    res = await db.execute(text("""
        SELECT
          id,
          kind::text   AS kind,
          signal::text AS signal,
          ST_Y(geom::geometry) AS lat,
          ST_X(geom::geometry) AS lng,
          created_at,
          phone,                  -- 👈 ici
          'new'::text AS status,
          -- si tu as déjà une jointure qui calcule photo_url, garde-la.
          NULL::text AS photo_url,
          EXTRACT(EPOCH FROM (NOW() - created_at))::int / 60 AS age_min
        FROM reports
        WHERE LOWER(TRIM(signal::text)) = 'cut'
        ORDER BY created_at DESC
        LIMIT :lim
    """), {"lim": limit})

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
            "phone": getattr(r, "phone", None),   # 👈 et ici dans le JSON
        })
    return {"items": items, "count": len(items)}
