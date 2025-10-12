# app/routes/map.py
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, bindparam
from sqlalchemy.types import Float
from app.db import get_db
import os

router = APIRouter()

POINTS_WINDOW_MIN = int(os.getenv("POINTS_WINDOW_MIN", "60"))   # durée d'affichage des derniers reports
MAX_REPORTS       = int(os.getenv("MAX_REPORTS", "300"))        # limite de sécurité

@router.get("/map")
async def map_endpoint(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    radius_km: float = Query(5.0, gt=0, le=100),
    db: AsyncSession = Depends(get_db),
):
    try:
        radius_m = float(radius_km * 1000.0)

        params = {
            "lat": lat,
            "lng": lng,
            "radius_m": radius_m,
            "win": POINTS_WINDOW_MIN,
            "max_reports": MAX_REPORTS,
        }

        # ---- OUTAGES (zones power/water) ----
        q_outages = text("""
            WITH center AS (
              SELECT ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography AS g
            )
            SELECT
              o.id,
              o.kind::text      AS kind,
              o.status::text    AS status,
              ST_Y(o.center::geometry) AS lat,
              ST_X(o.center::geometry) AS lng,
              o.radius_m,
              o.started_at,
              o.restored_at,
              o.label_override
            FROM outages o, center c
            WHERE ST_DWithin(o.center, c.g, CAST(:radius_m AS double precision))
            ORDER BY
              (o.status = 'ongoing') DESC,
              o.started_at DESC
        """).bindparams(bindparam("radius_m", type_=Float))
        res_out = await db.execute(q_outages, params)
        outages = [
            {
                "id": r.id,
                "kind": r.kind,
                "status": r.status,
                "center": {"lat": float(r.lat), "lng": float(r.lng)},
                "radius_m": int(r.radius_m),
                "started_at": r.started_at,
                "restored_at": r.restored_at,
                "label_override": r.label_override,
            }
            for r in res_out.fetchall()
        ]

        # ---- INCIDENTS (uniquement actifs) ----
        q_inc = text("""
            WITH center AS (
              SELECT ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography AS g
            )
            SELECT
              i.id,
              i.kind::text AS kind,
              i.active,
              ST_Y(i.center::geometry) AS lat,
              ST_X(i.center::geometry) AS lng,
              i.started_at,
              i.last_cut_at,
              i.ended_at
            FROM incidents i, center c
            WHERE i.active = true
              AND ST_DWithin(i.center, c.g, CAST(:radius_m AS double precision))
            ORDER BY i.started_at DESC
        """).bindparams(bindparam("radius_m", type_=Float))
        res_inc = await db.execute(q_inc, params)
        incidents = [
            {
                "id": r.id,
                "kind": r.kind,
                "active": r.active,
                "center": {"lat": float(r.lat), "lng": float(r.lng)},
                "started_at": r.started_at,
                "last_cut_at": r.last_cut_at,
                "ended_at": r.ended_at,
            }
            for r in res_inc.fetchall()
        ]

        # ---- LAST REPORTS (derniers points, tout le monde) ----
        q_rep = text("""
            WITH center AS (
              SELECT ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography AS g
            )
            SELECT
              r.id,
              r.kind::text   AS kind,
              r.signal::text AS signal,
              ST_Y(r.geom::geometry) AS lat,
              ST_X(r.geom::geometry) AS lng,
              r.created_at
            FROM reports r, center c
            WHERE r.created_at >= now() - ( :win || ' minutes')::interval
              AND ST_DWithin(r.geom::geography, c.g, CAST(:radius_m AS double precision))
            ORDER BY r.created_at DESC
            LIMIT :max_reports
        """).bindparams(bindparam("radius_m", type_=Float))
        res_rep = await db.execute(q_rep, params)
        last_reports = [
            {
                "id": r.id,
                "kind": r.kind,
                "signal": r.signal,
                "lat": float(r.lat),
                "lng": float(r.lng),
                "created_at": r.created_at,
            }
            for r in res_rep.fetchall()
        ]

        return {
            "outages": outages,
            "incidents": incidents,
            "last_reports": last_reports,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
