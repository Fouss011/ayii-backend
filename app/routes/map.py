# app/routes/map.py
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.db import get_db
import os

router = APIRouter()

POINTS_WINDOW_MIN = int(os.getenv("POINTS_WINDOW_MIN", "240"))
MAX_REPORTS       = int(os.getenv("MAX_REPORTS", "500"))

@router.get("/map")
async def map_endpoint(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    radius_km: float = Query(5.0, gt=0, le=50),
    response: Response = None,
    db: AsyncSession = Depends(get_db),
):
    try:
        # --- Outages (power/water) — status calculé depuis restored_at ---
        q_outages = text("""
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
        res_out = await db.execute(q_outages, {"lng": float(lng), "lat": float(lat), "r": float(radius_km * 1000.0)})
        outages = [
            {
                "id": r.id,
                "kind": r.kind,
                "status": r.status,
                "lat": float(r.lat),
                "lng": float(r.lng),
                "started_at": r.started_at,
                "restored_at": r.restored_at,
            }
            for r in res_out.fetchall()
        ]

        # --- Incidents (traffic/accident/fire/flood) — status calculé idem ---
        q_inc = text("""
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
        res_inc = await db.execute(q_inc, {"lng": float(lng), "lat": float(lat), "r": float(radius_km * 1000.0)})
        incidents = [
            {
                "id": r.id,
                "kind": r.kind,
                "status": r.status,
                "lat": float(r.lat),
                "lng": float(r.lng),
                "started_at": r.started_at,
                "restored_at": r.restored_at,
            }
            for r in res_inc.fetchall()
        ]

        # --- Derniers reports (fenêtre glissante) ---
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
        res_rep = await db.execute(q_rep, {"lng": float(lng), "lat": float(lat), "r": float(radius_km * 1000.0), "max": MAX_REPORTS})
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
