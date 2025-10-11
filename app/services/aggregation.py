# app/services/aggregation.py
import os
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.crud import expire_stale_outages, expire_incidents

# ---- Paramètres pilotés par ENV (modifiables sur Render) ----
CUT_WINDOW_HOURS          = int(os.getenv("CUT_WINDOW_HOURS", "3"))       # fenêtre pour re-open & clustering
CLUSTER_GRID_DEG          = float(os.getenv("CLUSTER_GRID_DEG", "0.003")) # ~300–330m
MIN_REPORTS               = int(os.getenv("MIN_REPORTS", "2"))            # nb de "cut" pour créer une zone
DEFAULT_RADIUS_M          = int(os.getenv("DEFAULT_RADIUS_M", "350"))
MERGE_DISTANCE_M          = int(os.getenv("MERGE_DISTANCE_M", "400"))
RESTORE_WINDOW_HOURS      = int(os.getenv("RESTORE_WINDOW_HOURS", "6"))
COOLDOWN_AFTER_RESTORE_MIN= int(os.getenv("COOLDOWN_AFTER_RESTORE_MIN", "10"))

# Nouveaux paramètres de stabilité
MIN_INCIDENT_LIFETIME_MIN = int(os.getenv("MIN_INCIDENT_LIFETIME_MIN", "20"))
MIN_OUTAGE_LIFETIME_MIN   = int(os.getenv("MIN_OUTAGE_LIFETIME_MIN", "20"))
RESTORE_CONFIRMATIONS     = int(os.getenv("RESTORE_CONFIRMATIONS", "2"))
OUTAGE_TTL_MIN            = int(os.getenv("OUTAGE_TTL_MIN", "180"))

async def run_aggregation(db: AsyncSession):
    # 0) RE-OPEN : si des "cut" récents réapparaissent près d'une zone restaurée
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
    await db.execute(reopen_sql)
    await db.commit()

    # 1) CLOSE OUTAGES (power/water) — confirmations + âge minimum + TTL dur
    close_outages_sql = text(f"""
        UPDATE outages o
           SET status = 'restored',
               restored_at = COALESCE(o.restored_at, now())
         WHERE o.status = 'ongoing'
           AND (
                -- Règle principale : assez de confirmations + âge minimum
                (
                  (SELECT COUNT(*)
                     FROM reports r
                    WHERE r.kind::text = o.kind::text
                      AND r.signal::text = 'restored'
                      AND r.created_at >= o.started_at
                      AND ST_DWithin(r.geom::geography, o.center, o.radius_m)
                  ) >= {RESTORE_CONFIRMATIONS}
                  AND now() - o.started_at >= interval '{MIN_OUTAGE_LIFETIME_MIN} minutes'
                )
                OR
                -- TTL dur (sécurité)
                (now() - o.started_at >= interval '{OUTAGE_TTL_MIN} minutes')
           );
    """)
    await db.execute(close_outages_sql)
    await db.commit()

    # 2) CREATE OUTAGES — clustering des "cut" récents
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
            CAST(c.kind::text AS outage_kind),
            'ongoing',
            ST_SetSRID(c.center_geom, 4326)::geography,
            {DEFAULT_RADIUS_M},
            now()
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
    await db.execute(create_sql)
    await db.commit()

    # 3) CLOSE INCIDENTS (traffic/accident/fire/flood) — grace period + restored proche
    close_incidents_sql = text(f"""
        UPDATE incidents i
           SET active = FALSE,
               ended_at = COALESCE(i.ended_at, now())
         WHERE i.active = TRUE
           AND now() - COALESCE(i.last_cut_at, i.started_at) >= interval '{MIN_INCIDENT_LIFETIME_MIN} minutes'
           AND EXISTS (
                SELECT 1
                  FROM reports r
                 WHERE r.kind::text = i.kind::text
                   AND r.signal::text = 'restored'
                   AND r.created_at >= COALESCE(i.last_cut_at, i.started_at)
                   AND ST_DWithin(r.geom::geography, i.center, 800)
           );
    """)
    await db.execute(close_incidents_sql)
    await db.commit()

    # 4) Expirations/housekeeping complémentaires (si tu en as besoin en plus des règles ci-dessus)
    await expire_stale_outages(db)
    await expire_incidents(db)
    await db.commit()
