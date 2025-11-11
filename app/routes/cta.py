# app/routes/cta.py
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
import os

from app.db import get_db  # tu l'as déjà dans les autres routes

router = APIRouter(tags=["CTA"])

@router.get("/cta/incidents")
async def cta_incidents(
    request: Request,
    status: str = Query("", description="new|confirmed|resolved (pas encore filtré)"),
    limit: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    # même contrôle que ton dashboard
    admin_tok = (os.getenv("ADMIN_TOKEN") or "").strip()
    req_tok = (request.headers.get("x-admin-token") or "").strip()
    if admin_tok and req_tok != admin_tok:
        raise HTTPException(status_code=401, detail="invalid admin token")

    res = await db.execute(text("""
        SELECT
          id,
          kind::text   AS kind,
          signal::text AS signal,
          ST_Y(geom::geometry) AS lat,
          ST_X(geom::geometry) AS lng,
          created_at,
          phone,                  -- 👈 on renvoie le numéro
          'new'::text AS status,
          NULL::text AS photo_url,
          1::int   AS reports_count,
          0::int   AS attachments_count,
          EXTRACT(EPOCH FROM (NOW() - created_at))::int / 60 AS age_min
        FROM reports
        WHERE LOWER(TRIM(signal::text)) = 'cut'
        ORDER BY created_at DESC
        LIMIT :lim
    """), {"lim": limit})
    rows = res.mappings().all()
    return {"items": [dict(r) for r in rows]}
