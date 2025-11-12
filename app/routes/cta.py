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

    # On renvoie bien r.phone et une pièce jointe récente si elle existe
    q = text("""
        WITH att AS (
          SELECT
            kind::text          AS kind,
            round(CAST(ST_Y(geom::geometry) AS numeric), 5) AS lat_r,
            round(CAST(ST_X(geom::geometry) AS numeric), 5) AS lng_r,
            url,
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
          r.phone,                           -- 👈 téléphone
          'new'::text AS status,
          (
            SELECT a.url
            FROM att a
            WHERE a.kind  = r.kind::text
              AND round(CAST(ST_Y(r.geom::geometry) AS numeric), 5) = a.lat_r
              AND round(CAST(ST_X(r.geom::geometry) AS numeric), 5) = a.lng_r
            ORDER BY a.created_at DESC
            LIMIT 1
          ) AS photo_url,
          EXTRACT(EPOCH FROM (NOW() - r.created_at))::int / 60 AS age_min
        FROM reports r
        WHERE LOWER(TRIM(r.signal::text)) = 'cut'
        ORDER BY r.created_at DESC
        LIMIT :lim
    """)

    res = await db.execute(q, {"lim": int(limit)})

    items = []
    for r in res.fetchall():
        items.append({
            "id": r.id,
            "kind": r.kind,
            "signal": r.signal,
            "lat": float(r.lat),
            "lng": float(r.lng),
            "created_at": r.created_at,
            "status": r.status,           # 'new'
            "photo_url": r.photo_url,     # image ou vidéo (mp4/webm/mov)
            "age_min": int(r.age_min) if r.age_min is not None else None,
            "phone": getattr(r, "phone", None),  # 👈 exposé au dashboard
        })

    return {"items": items, "count": len(items)}


@router.get("/cta/incidents_v2")
async def cta_incidents_v2(
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

    q = text("""
        WITH att AS (
          SELECT
            kind::text          AS kind,
            round(CAST(ST_Y(geom::geometry) AS numeric), 5) AS lat_r,
            round(CAST(ST_X(geom::geometry) AS numeric), 5) AS lng_r,
            url,
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
          r.phone,                           -- 👈 téléphone
          'new'::text AS status,
          (
            SELECT a.url
            FROM att a
            WHERE a.kind  = r.kind::text
              AND round(CAST(ST_Y(r.geom::geometry) AS numeric), 5) = a.lat_r
              AND round(CAST(ST_X(r.geom::geometry) AS numeric), 5) = a.lng_r
            ORDER BY a.created_at DESC
            LIMIT 1
          ) AS photo_url,
          EXTRACT(EPOCH FROM (NOW() - r.created_at))::int / 60 AS age_min
        FROM reports r
        WHERE LOWER(TRIM(r.signal::text)) = 'cut'
        ORDER BY r.created_at DESC
        LIMIT :lim
    """)

    res = await db.execute(q, {"lim": int(limit)})

    items = []
    for row in res.fetchall():
        m = row._mapping  # robuste pour accéder aux colonnes
        items.append({
            "id": m["id"],
            "kind": m["kind"],
            "signal": m["signal"],
            "lat": float(m["lat"]),
            "lng": float(m["lng"]),
            "created_at": m["created_at"],
            "status": m["status"],           # 'new'
            "photo_url": m["photo_url"],     # image ou vidéo
            "age_min": int(m["age_min"]) if m["age_min"] is not None else None,
            "phone": m.get("phone", None),   # 👈 clé toujours présente
        })

    return {"api_version": "v2", "items": items, "count": len(items)}
