# app/routes/map.py
from fastapi import APIRouter, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_db
from sqlalchemy import text

router = APIRouter()

@router.get("/map")
async def get_map(
    lat: float = Query(...),
    lng: float = Query(...),
    radius_km: float = Query(5.0)
):
    try:
        async with get_db() as db:  # récupère la session
            meters = radius_km * 1000.0

            # Outages (zones)
            sql_outages = text("""
                WITH me AS (
                  SELECT ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography AS g
                )
                SELECT
                  id, kind, status,
                  ST_Y(center::geometry) AS lat,
                  ST_X(center::geometry) AS lng,
                  radius_m, started_at, restored_at, label_override
                FROM outages
                WHERE ST_DWithin(center, (SELECT g FROM me), :meters + radius_m)
                ORDER BY started_at DESC
            """)
            res_out = await db.execute(sql_outages, {"lat": lat, "lng": lng, "meters": meters})
            outages = [
                {
                    "id": r.id,
                    "kind": r.kind,
                    "status": r.status,
                    "center": {"lat": r.lat, "lng": r.lng},
                    "radius_m": r.radius_m,
                    "started_at": r.started_at,
                    "restored_at": r.restored_at,
                    "label_override": r.label_override,
                }
                for r in res_out
            ]

            # Last reports
            sql_reports = text("""
                SELECT id, kind, signal,
                       ST_Y(geom::geometry) AS lat,
                       ST_X(geom::geometry) AS lng,
                       created_at, user_id
                FROM reports
                WHERE created_at > now() - interval '12 hours'
                ORDER BY created_at DESC
                LIMIT 200
            """)
            res_rep = await db.execute(sql_reports)
            last_reports = [dict(r._mapping) for r in res_rep]

            # Incidents
            sql_incidents = text("""
                SELECT id, kind, active,
                       ST_Y(center::geometry) AS lat,
                       ST_X(center::geometry) AS lng,
                       created_at, last_report_at, cleared_at
                FROM incidents
                WHERE active = true
                ORDER BY created_at DESC
            """)
            res_inc = await db.execute(sql_incidents)
            incidents = [
                {
                    "id": r.id,
                    "kind": r.kind,
                    "active": r.active,
                    "center": {"lat": r.lat, "lng": r.lng},
                    "created_at": r.created_at,
                    "last_report_at": r.last_report_at,
                    "cleared_at": r.cleared_at,
                }
                for r in res_inc
            ]

            return {"outages": outages, "last_reports": last_reports, "incidents": incidents}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
