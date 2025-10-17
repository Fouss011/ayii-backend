# app/services/aggregation.py
import os
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.crud import expire_stale_outages, expire_incidents

# -------- Parameters (override via env if needed) ----------
LOG_AGG = os.getenv("LOG_AGG", "0") == "1"

# Window for considering CUT reports to (re)build zones (minutes)
CUT_WINDOW_MIN = int(os.getenv("CUT_WINDOW_MIN", "30"))
# Minimal number of CUT reports to form a zone
MIN_REPORTS = int(os.getenv("OUTAGE_MIN_REPORTS", "3"))
# Spatial clustering distance (meters)
CLUSTER_WITHIN_M = int(os.getenv("OUTAGE_CLUSTER_M", "300"))
# Zone radius (meters) shown on map
DEFAULT_RADIUS_M = int(os.getenv("OUTAGE_RADIUS_M", "350"))
# Distance to match a zone when a RESTORED arrives (meters)
MATCH_RESTORE_M = int(os.getenv("OUTAGE_RESTORE_MATCH_M", "350"))
# Cooldown to avoid re-opening a just-restored zone too fast (minutes)
COOLDOWN_AFTER_RESTORE_MIN = int(os.getenv("OUTAGE_COOLDOWN_MIN", "5"))

async def run_aggregation(db: AsyncSession) -> None:
    """Rebuild active outages from recent CUT reports and strictly close them when:
      - a RESTORED report is seen near the zone, OR
      - the number of recent CUT reports supporting the zone goes below MIN_REPORTS.
    Also expires incidents/outages via crud helpers when enabled."""

    # 0) Safety: ensure columns
    await db.execute(text("ALTER TABLE outages  ADD COLUMN IF NOT EXISTS started_at timestamp NULL"))
    await db.execute(text("ALTER TABLE outages  ADD COLUMN IF NOT EXISTS restored_at timestamp NULL"))
    await db.execute(text("ALTER TABLE incidents ADD COLUMN IF NOT EXISTS restored_at timestamp NULL"))
    await db.commit()

    # 1) Close zones that received any RESTORED near them (strict)
    close_by_restore = text(f"""
        UPDATE outages o
           SET restored_at = COALESCE(o.restored_at, NOW())
         WHERE o.restored_at IS NULL
           AND EXISTS (
                SELECT 1
                  FROM reports r
                 WHERE r.kind::text = o.kind::text
                   AND LOWER(TRIM(r.signal::text)) = 'restored'
                   AND r.created_at >= NOW() - INTERVAL '{CUT_WINDOW_MIN} minutes'
                   AND ST_DWithin(r.geom::geography, o.center, {MATCH_RESTORE_M})
           )
    """)
    res = await db.execute(close_by_restore)
    if LOG_AGG: print(f"[agg] outages closed by RESTORED -> {res.rowcount or 0}")
    await db.commit()

    # 2) Build clusters from recent CUT reports (power/water only)
    create_tmp = text(f"""
        DROP TABLE IF EXISTS _tmp_outage_clusters;
        CREATE TEMP TABLE _tmp_outage_clusters AS
        WITH recent AS (
          SELECT id, kind::text AS kind, geom::geometry AS g
            FROM reports
           WHERE LOWER(TRIM(signal::text)) = 'cut'
             AND created_at >= NOW() - INTERVAL '{CUT_WINDOW_MIN} minutes'
             AND kind IN ('power','water')
        ),
        grp AS (
          SELECT
            kind,
            ST_SnapToGrid(g,  {CLUSTER_WITHIN_M}/111320.0, {CLUSTER_WITHIN_M}/111320.0) AS cell,
            COUNT(*) AS n,
            ST_Centroid(ST_Collect(g)) AS center_geom
          FROM recent
          GROUP BY kind, ST_SnapToGrid(g, {CLUSTER_WITHIN_M}/111320.0, {CLUSTER_WITHIN_M}/111320.0)
        )
        SELECT kind, n, center_geom
          FROM grp
         WHERE n >= {MIN_REPORTS};
    """)
    await db.execute(create_tmp)
    await db.commit()

    # 3) Close zones no longer supported by >= MIN_REPORTS CUTs
    restore_when_below_threshold = text(f"""
        UPDATE outages o
           SET restored_at = COALESCE(o.restored_at, NOW())
         WHERE o.restored_at IS NULL
           AND NOT EXISTS (
                SELECT 1
                  FROM _tmp_outage_clusters c
                 WHERE c.kind::text = o.kind::text
                   AND ST_DWithin(o.center, ST_SetSRID(c.center_geom,4326)::geography, {MATCH_RESTORE_M})
           )
    """)
    res = await db.execute(restore_when_below_threshold)
    if LOG_AGG: print(f"[agg] outages closed by threshold -> {res.rowcount or 0}")
    await db.commit()

    # 4) Create or (re)open zones from clusters, respecting cooldown
    create_or_refresh = text(f"""
        INSERT INTO outages(kind, center, started_at, restored_at, radius_m)
        SELECT c.kind,
               ST_SetSRID(c.center_geom,4326)::geography,
               NOW(), NULL,
               {DEFAULT_RADIUS_M}
          FROM _tmp_outage_clusters c
          WHERE NOT EXISTS (
              SELECT 1
                FROM outages o2
               WHERE o2.kind::text = c.kind::text
                 AND ST_DWithin(o2.center, ST_SetSRID(c.center_geom,4326)::geography, {MATCH_RESTORE_M})
                 AND o2.restored_at IS NOT NULL
                 AND o2.restored_at > NOW() - INTERVAL '{COOLDOWN_AFTER_RESTORE_MIN} minutes'
          );

        -- Re-open zones beyond cooldown if cluster re-appears
        UPDATE outages o
           SET restored_at = NULL
         WHERE o.restored_at IS NOT NULL
           AND EXISTS (
                SELECT 1
                  FROM _tmp_outage_clusters c
                 WHERE c.kind::text = o.kind::text
                   AND ST_DWithin(o.center, ST_SetSRID(c.center_geom,4326)::geography, {MATCH_RESTORE_M})
                   AND o.restored_at <= NOW() - INTERVAL '{COOLDOWN_AFTER_RESTORE_MIN} minutes'
           );
    """)
    await db.execute(create_or_refresh)
    await db.commit()

    # 5) Housekeeping (optional)
    try:
        c1 = await expire_stale_outages(db)
    except Exception:
        c1 = None
    try:
        c2 = await expire_incidents(db)
    except Exception:
        c2 = None
    if LOG_AGG:
        if c1 is not None: print(f"[agg] expire_stale_outages -> {c1}")
        if c2 is not None: print(f"[agg] expire_incidents -> {c2}")
