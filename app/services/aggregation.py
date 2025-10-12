# app/services/aggregation.py
import os
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.crud import expire_stale_outages, expire_incidents

# Flags/env de stabilité
AUTO_EXPIRE_ENABLED = os.getenv("AUTO_EXPIRE_ENABLED", "1") != "0"
LOG_AGG = os.getenv("LOG_AGG", "0") == "1"

# Paramètres
CUT_WINDOW_HOURS = 3
CLUSTER_GRID_DEG = 0.003     # ~300–330m
MIN_REPORTS = 2
DEFAULT_RADIUS_M = 350
MERGE_DISTANCE_M = 400
RESTORE_WINDOW_HOURS = 6
COOLDOWN_AFTER_RESTORE_MIN = 10

async def run_aggregation(db: AsyncSession):
    # 0) Re-open: un nouveau "cut" près d'une zone restaurée -> repasse en ongoing
    reopen_sql = text(f"""
        WITH recent_cut AS (
            SELECT kind, geom::geography AS g, created_at
              FROM reports
             WHERE kind::text IN ('power','water')
               AND signal::text = 'cut'
               AND created_at > now() - interval '{CUT_WINDOW_HOURS} hours'
        )
        UPDATE outages o
           SET status = 'ongoing',
               restored_at = NULL
         WHERE o.status = 'restored'
           AND EXISTS (
                SELECT 1
                  FROM recent_cut r
                 WHERE r.kind::text = o.kind::text
                   AND r.created_at > COALESCE(o.restored_at, now() - interval '100 years')
                   AND ST_DWithin(
                         r.g,
                         o.center,
                         LEAST(o.radius_m, {MERGE_DISTANCE_M})
                       )
           );
    """)
    res = await db.execute(reopen_sql)
    if LOG_AGG: print(f"[agg] reopen outages -> {res.rowcount}")
    await db.commit()

    # 1) Close par "restored" récents
    close_sql = text(f"""
        UPDATE outages o
           SET status = 'restored',
               restored_at = COALESCE(o.restored_at, now())
         WHERE o.status = 'ongoing'
           AND EXISTS (
                SELECT 1
                  FROM reports r
                 WHERE r.kind::text   = o.kind::text
                   AND r.signal::text = 'restored'
                   AND r.created_at > now() - interval '{RESTORE_WINDOW_HOURS} hours'
                   AND ST_DWithin(
                         r.geom::geography,
                         o.center,
                         LEAST(o.radius_m, 300)
                       )
           );
    """)
    res = await db.execute(close_sql)
    if LOG_AGG: print(f"[agg] close outages (restore) -> {res.rowcount}")
    await db.commit()

    # 2) Création de zones par clustering de "cut" récents
    create_sql = text(f"""
        WITH recent AS (
            SELECT kind, geom::geometry AS g
              FROM reports
             WHERE kind::text IN ('power','water')
               AND signal::text = 'cut'
               AND created_at > now() - interval '{CUT_WINDOW_HOURS} hours'
        ),
        clusters AS (
            SELECT kind,
                   ST_SnapToGrid(g, {CLUSTER_GRID_DEG}) AS cell,
                   COUNT(*) AS c,
                   ST_Centroid(ST_Collect(g)) AS center_geom
              FROM recent
             GROUP BY kind, ST_SnapToGrid(g, {CLUSTER_GRID_DEG})
            HAVING COUNT(*) >= {MIN_REPORTS}
        )
        INSERT INTO outages (kind, status, center, radius_m, started_at)
        SELECT
            CAST(c.kind::text AS outage_kind)
          , 'ongoing'
          , ST_SetSRID(c.center_geom, 4326)::geography
          , {DEFAULT_RADIUS_M}
          , now()
          FROM clusters c
         WHERE NOT EXISTS (
                SELECT 1
                  FROM outages o
                 WHERE o.kind::text = c.kind::text
                   AND o.status = 'ongoing'
                   AND ST_DWithin(
                         o.center,
                         ST_SetSRID(c.center_geom, 4326)::geography,
                         {MERGE_DISTANCE_M}
                       )
           )
           AND NOT EXISTS (
                SELECT 1
                  FROM outages o2
                 WHERE o2.kind::text = c.kind::text
                   AND o2.status = 'restored'
                   AND o2.restored_at > now() - interval '{COOLDOWN_AFTER_RESTORE_MIN} minutes'
                   AND ST_DWithin(
                         o2.center,
                         ST_SetSRID(c.center_geom, 4326)::geography,
                         {MERGE_DISTANCE_M}
                       )
           );
    """)
    res = await db.execute(create_sql)
    if LOG_AGG: print(f"[agg] create outages (clusters) -> {res.rowcount}")
    await db.commit()

    # 4) Expirations / housekeeping (désactivables)
    if AUTO_EXPIRE_ENABLED:
        c1 = await expire_stale_outages(db)
        c2 = await expire_incidents(db)
        if LOG_AGG:
            if c1 is not None: print(f"[agg] expire_stale_outages -> {c1}")
            if c2 is not None: print(f"[agg] expire_incidents -> {c2}")
        await db.commit()
    else:
        if LOG_AGG:
            print("[agg] auto-expire disabled (AUTO_EXPIRE_ENABLED=0)")
