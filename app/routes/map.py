# app/routes/map.py
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.db import get_db
import os

router = APIRouter()

POINTS_WINDOW_MIN = int(os.getenv("POINTS_WINDOW_MIN", "240"))
MAX_REPORTS       = int(os.getenv("MAX_REPORTS", "500"))

async def fetch_outages(db: AsyncSession, lat: float, lng: float, r_m: float):
    # Essai complet (avec started_at / restored_at)
    q_full = text("""
        WITH me AS (
          SELECT ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography AS g
        )
        SELECT
          id,
          kind::text AS kind,
          CASE WHEN restored_at IS NULL THEN 'active' ELSE 'restored' END AS status,
          ST_Y(center::geometry) AS lat,
          ST_X(center::geometry) AS lng,
          started_at,
          restored_at
        FROM outages
        WHERE ST_DWithin(center, (SELECT g FROM me), :r)
        ORDER BY started_at DESC
    """)
    # Fallback minimal (si colonnes absentes)
    q_min = text("""
        WITH me AS (
          SELECT ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography AS g
        )
        SELECT
          id,
          kind::text AS kind,
          'active' AS status,
          ST_Y(center::geometry) AS lat,
          ST_X(center::geometry) AS lng,
          NULL::timestamp AS started_at,
          NULL::timestamp AS restored_at
        FROM outages
        WHERE ST_DWithin(center, (SELECT g FROM me), :r)
        ORDER BY id DESC
    """)
    try:
        res = await db.execute(q_full, {"lng": lng, "lat": lat, "r": r_m})
    except Exception as e:
        if "UndefinedColumn" not in str(e):
            raise
        res = await db.execute(q_min, {"lng": lng, "lat": lat, "r": r_m})
    rows = res.fetchall()
    return [
        {
            "id": r.id,
            "kind": r.kind,
            "status": r.status,
            "lat": float(r.lat),
            "lng": float(r.lng),
            "started_at": getattr(r, "started_at", None),
            "restored_at": getattr(r, "restored_at", None),
        }
        for r in rows
    ]

async def fetch_incidents(db: AsyncSession, lat: float, lng: float, r_m: float):
    q_full = text("""
        WITH me AS (
          SELECT ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography AS g
        )
        SELECT
          id,
          kind::text AS kind,
          CASE WHEN restored_at IS NULL THEN 'active' ELSE 'restored' END AS status,
          ST_Y(center::geometry) AS lat,
          ST_X(center::geometry) AS lng,
          started_at,
          restored_at
        FROM incidents
        WHERE ST_DWithin(center, (SELECT g FROM me), :r)
        ORDER BY started_at DESC
    """)
    q_min = text("""
        WITH me AS (
          SELECT ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography AS g
        )
        SELECT
          id,
          kind::text AS kind,
          'active' AS status,
          ST_Y(center::geometry) AS lat,
          ST_X(center::geometry) AS lng,
          NULL::timestamp AS started_at,
          NULL::timestamp AS restored_at
        FROM incidents
        WHERE ST_DWithin(center, (SELECT g FROM me), :r)
        ORDER BY id DESC
    """)
    try:
        res = await db.execute(q_full, {"lng": lng, "lat": lat, "r": r_m})
    except Exception as e:
        if "UndefinedColumn" not in str(e):
            raise
        res = await db.execute(q_min, {"lng": lng, "lat": lat, "r": r_m})
    rows = res.fetchall()
    return [
        {
            "id": r.id,
            "kind": r.kind,
            "status": r.status,
            "lat": float(r.lat),
            "lng": float(r.lng),
            "started_at": getattr(r, "started_at", None),
            "restored_at": getattr(r, "restored_at", None),
        }
        for r in rows
    ]

@router.get("/map")
async def map_endpoint(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    radius_km: float = Query(5.0, gt=0, le=50),
    response: Response = None,
    db: AsyncSession = Depends(get_db),
):
    try:
        r_m = float(radius_km * 1000.0)

        outages = await fetch_outages(db, lat, lng, r_m)
        incidents = await fetch_incidents(db, lat, lng, r_m)

        # reports (garde la version "complète" — normalement created_at/geo existent)
        q_rep = text(f"""
            WITH me AS (
              SELECT ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography AS g
            )
            SELECT
              id,
              kind::text AS kind,
              signal::text AS signal,
              ST_Y(geo::geometry) AS lat,
              ST_X(geo::geometry) AS lng,
              user_id,
              created_at
            FROM reports
            WHERE ST_DWithin(geo, (SELECT g FROM me), :r)
              AND created_at > NOW() - INTERVAL '{POINTS_WINDOW_MIN} minutes'
            ORDER BY created_at DESC
            LIMIT :max
        """)
        res_rep = await db.execute(q_rep, {"lng": lng, "lat": lat, "r": r_m, "max": MAX_REPORTS})
        last_reports = [
            {
                "id": r.id,
                "kind": r.kind,
                "signal": r.signal,
                "lat": float(r.lat),
                "lng": float(r.lng),
                "user_id": r.user_id,
                "created_at": r.created_at,
            }
            for r in res_rep.fetchall()
        ]

        payload = {
            "outages": outages,
            "incidents": incidents,
            "last_reports": last_reports,
            "server_now": __import__("datetime").datetime.utcnow().isoformat() + "Z",
        }
        if response is not None:
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
            response.headers["Pragma"] = "no-cache"
        return payload

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
