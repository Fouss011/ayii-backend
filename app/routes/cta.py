# app/routes/cta.py
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.db import get_db

router = APIRouter(tags=["CTA"])

@router.get("/cta/incidents")
async def cta_incidents(
    request: Request,
    status: str = Query("", description="new|confirmed|resolved (placeholder)"),
    limit: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    filter_by_status = status.strip().lower() in {"new", "confirmed", "resolved"}
    where_status = "AND COALESCE(r.status,'new') = :status" if filter_by_status else ""

    sql = f"""
    WITH base AS (
      SELECT
        r.id,
        r.kind::text AS kind,
        r.signal::text AS signal,
        ST_Y((r.geom::geometry)) AS lat,
        ST_X((r.geom::geometry)) AS lng,
        r.created_at,
        COALESCE(r.status,'new') AS status,
        r.phone                                  -- 👈 ajouté
      FROM reports r
      WHERE LOWER(TRIM(r.signal::text)) = 'cut'
        {where_status}
      ORDER BY r.created_at DESC
      LIMIT :limit
    ),
    with_photo AS (
      SELECT
        b.*,
        a.public_url AS photo_url,
        EXTRACT(EPOCH FROM (NOW() - b.created_at))::int/60 AS age_min
      FROM base b
      LEFT JOIN LATERAL (
        SELECT att.public_url
        FROM attachments att
        WHERE att.kind = b.kind
          AND att.created_at >= b.created_at - INTERVAL '48 hours'
          AND att.created_at <= NOW()
          AND ST_DWithin((att.geom::geography), (ST_SetSRID(ST_MakePoint(b.lng,b.lat),4326)::geography), 120)
        ORDER BY att.created_at DESC
        LIMIT 1
      ) a ON TRUE
    )
    SELECT * FROM with_photo
    """
    params = {"limit": limit}
    if filter_by_status:
        params["status"] = status.strip().lower()

    res = await db.execute(text(sql), params)
    rows = res.fetchall()

    items = []
    for r in rows:
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
            "phone": getattr(r, "phone", None),  # 👈 maintenant présent dans le JSON
        })
    return {"items": items, "count": len(items)}
