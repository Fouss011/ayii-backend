# app/crud.py
from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import text, bindparam
from sqlalchemy.types import Float
from sqlalchemy.ext.asyncio import AsyncSession


# --- Introspection (pour gérer enums ou text dynamiquement) ----------------

async def get_column_typename(db: AsyncSession, table: str, column: str) -> str:
    q = text("""
        SELECT t.typname
        FROM pg_attribute a
        JOIN pg_class c ON a.attrelid = c.oid
        JOIN pg_type  t ON a.atttypid = t.oid
        JOIN pg_namespace n ON c.relnamespace = n.oid
        WHERE n.nspname = 'public' AND c.relname = :table AND a.attname = :col
    """)
    r = await db.execute(q, {"table": table, "col": column})
    return r.scalar_one()

async def is_enum_typename(db: AsyncSession, typname: str) -> bool:
    q = text("""
        SELECT EXISTS (
          SELECT 1
          FROM pg_type t
          JOIN pg_enum e ON e.enumtypid = t.oid
          WHERE t.typname = :t
        )
    """)
    r = await db.execute(q, {"t": typname})
    return bool(r.scalar_one())


# --- Constantes & sets -----------------------------------------------------

KINDS_OUTAGE = {"power", "water"}
INCIDENT_KINDS = {"traffic", "accident", "fire", "flood"}

# rayon max qu’on “cherche” autour d’un point pour fermer une zone
CLOSE_SEARCH_METERS = 3000.0
CLOSE_FACTOR = 1.5     # on accepte si dist <= 1.5 * radius
CLOSE_HARDCAP = 1500.0 # ou si dist <= 1500 m


# --- Inserts / Reports -----------------------------------------------------

from sqlalchemy.dialects.postgresql import UUID

async def insert_report(
    db: AsyncSession,
    *,
    kind: str,
    signal: str,
    lat: float,
    lng: float,
    accuracy_m: Optional[int] = None,
    note: Optional[str] = None,
    photo_url: Optional[str] = None,
    user_id: Optional[str] = None,
) -> str:
    """
    Insert dans reports (en tenant compte des enums dynamiques) + actions auto.
    Garantit que user_id respecte la FK vers app_users (upsert si besoin).
    """

    # 0) si user_id fourni -> s'assurer que app_users contient la clé
    if user_id:
        try:
            await db.execute(
                text("INSERT INTO app_users (id) VALUES (CAST(:uid AS uuid)) ON CONFLICT (id) DO NOTHING"),
                {"uid": user_id},
            )
            await db.commit()
        except Exception:
            await db.rollback()
            # on continue; l'insert échouera si la FK n'est pas satisfaite

    # 1) introspection des types (enum/text) pour kind/signal
    kind_typ = await get_column_typename(db, "reports", "kind")
    sig_typ  = await get_column_typename(db, "reports", "signal")
    kind_is_enum = await is_enum_typename(db, kind_typ)
    sig_is_enum  = await is_enum_typename(db, sig_typ)

    kind_cast = kind_typ if kind_is_enum else "text"
    sig_cast  = sig_typ  if sig_is_enum  else "text"

    # 2) insert (⚠️ on typpe user_id et on le CAST directement)
    insert_sql = text(f"""
        INSERT INTO reports (kind, signal, geom, accuracy_m, note, photo_url, user_id)
        VALUES (
            CAST(:kind AS {kind_cast}),
            CAST(:signal AS {sig_cast}),
            ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography,
            :accuracy_m, :note, :photo_url,
            CAST(:user_id AS uuid)
        )
        RETURNING id
    """).bindparams(
        bindparam("user_id", type_=UUID(as_uuid=False))
    )

    try:
        res = await db.execute(insert_sql, {
            "kind": kind, "signal": signal, "lat": lat, "lng": lng,
            "accuracy_m": accuracy_m, "note": note, "photo_url": photo_url,
            "user_id": user_id  # None → CAST(NULL AS uuid) = NULL ; sinon string uuid ok
        })
        report_id = res.scalar_one()
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    # 3) actions auto
    try:
        if signal == "restored" and kind in KINDS_OUTAGE:
            await close_nearest_outage_on_restored(db, kind, lat, lng)

        if signal == "cut" and kind in INCIDENT_KINDS:
            await upsert_incident_from_report(db, kind, lat, lng)

        if signal == "restored" and kind in INCIDENT_KINDS:
            await clear_nearest_incident(db, kind, lat, lng)

        await db.commit()
    except Exception:
        await db.rollback()

    return report_id



# --- Map / lecture ---------------------------------------------------------

async def get_outages_in_radius(
    db: AsyncSession, lat: float, lng: float, radius_km: float
) -> Dict[str, Any]:
    meters = float(radius_km * 1000.0)

    # Outages (ongoing/restored)
    q_outages = text("""
        WITH me AS (
          SELECT ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography AS g
        )
        SELECT
          id, kind, status,
          ST_Y(center::geometry) AS lat,
          ST_X(center::geometry) AS lng,
          radius_m, started_at, restored_at, label_override
        FROM outages
        WHERE ST_DWithin(
            center,
            (SELECT g FROM me),
            CAST(:meters AS double precision) + radius_m
        )
        ORDER BY started_at DESC
    """).bindparams(bindparam("meters", type_=Float))

    out_res = await db.execute(q_outages, {"lat": lat, "lng": lng, "meters": meters})
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
        for r in out_res.fetchall()
    ]

    # Derniers reports (pour les pins)
    q_last = text("""
        WITH me AS (
          SELECT ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography AS g
        )
        SELECT
          id, kind, signal,
          ST_Y(geom::geometry) AS lat,
          ST_X(geom::geometry) AS lng,
          created_at,
          user_id
        FROM reports
        WHERE ST_DWithin(
            geom,
            (SELECT g FROM me),
            CAST(:meters AS double precision)
        )
        ORDER BY created_at DESC
        LIMIT 80
    """).bindparams(bindparam("meters", type_=Float))

    last_res = await db.execute(q_last, {"lat": lat, "lng": lng, "meters": meters})
    last_reports = [
        {
            "id": r.id,
            "kind": r.kind,
            "signal": r.signal,
            "lat": float(r.lat),
            "lng": float(r.lng),
            "created_at": r.created_at,
            "user_id": r.user_id,
        }
        for r in last_res.fetchall()
    ]

    # Incidents actifs
    q_inc = text("""
        WITH me AS (
          SELECT ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography AS g
        )
        SELECT id, kind, active,
               ST_Y(center::geometry) AS lat,
               ST_X(center::geometry) AS lng,
               created_at, last_report_at, cleared_at
          FROM incidents
         WHERE active = true
           AND ST_DWithin(
                 center,
                 (SELECT g FROM me),
                 CAST(:meters AS double precision)
               )
         ORDER BY last_report_at DESC NULLS LAST, created_at DESC
    """).bindparams(bindparam("meters", type_=Float))

    inc_res = await db.execute(q_inc, {"lat": lat, "lng": lng, "meters": meters})
    incidents = [
        {
            "id": r.id,
            "kind": r.kind,
            "active": r.active,
            "center": {"lat": float(r.lat), "lng": float(r.lng)},
            "created_at": r.created_at,
            "last_report_at": r.last_report_at,
            "cleared_at": r.cleared_at,
        }
        for r in inc_res.fetchall()
    ]

    return {"outages": outages, "last_reports": last_reports, "incidents": incidents}


# --- Fermeture tolérante des zones (rétabli) -------------------------------

async def close_nearest_outage_on_restored(
    db: AsyncSession, kind: str, lat: float, lng: float
) -> Optional[str]:
    """
    Cherche la zone 'ongoing' la plus proche et la ferme si l’utilisateur
    clique à <= 1.5 * radius OU <= 1500 m (le plus permissif).
    """
    q = text("""
        WITH me AS (
          SELECT ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography AS g
        ),
        cand AS (
          SELECT id, radius_m,
                 ST_Distance(center, (SELECT g FROM me)) AS dist
            FROM outages
           WHERE kind::text = :kind AND status='ongoing'    -- << cast text
             AND ST_DWithin(center, (SELECT g FROM me), CAST(:search_m AS double precision))
           ORDER BY center::geometry <-> (SELECT g::geometry FROM me)
           LIMIT 1
        )
        UPDATE outages o
           SET status='restored',
               restored_at = NOW()
          FROM cand
         WHERE o.id = cand.id
           AND (cand.dist <= cand.radius_m * :factor OR cand.dist <= CAST(:hard_cap AS double precision))
        RETURNING o.id
    """).bindparams(
        bindparam("search_m", type_=Float),
        bindparam("hard_cap", type_=Float),
        bindparam("factor", type_=Float),
    )

    res = await db.execute(q, {
        "kind": kind,
        "lat": lat,
        "lng": lng,
        "search_m": float(CLOSE_SEARCH_METERS),
        "factor": float(CLOSE_FACTOR),
        "hard_cap": float(CLOSE_HARDCAP),
    })
    return res.scalar_one_or_none()


# --- Incidents : upsert/clear + TTL ---------------------------------------

async def upsert_incident_from_report(
    db: AsyncSession, kind: str, lat: float, lng: float
) -> str:
    """
    Quand on reçoit un report 'cut' d’un incident, on active / rafraîchit un incident
    proche (≤ 500 m) ; sinon on en crée un.
    """
    q = text("""
        WITH me AS (
          SELECT ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography AS g
        ),
        cand AS (
          SELECT id
            FROM incidents
           WHERE kind::text = :kind AND active=true    -- << cast text
             AND ST_DWithin(center, (SELECT g FROM me), CAST(500 AS double precision))
           ORDER BY center::geometry <-> (SELECT g::geometry FROM me)
           LIMIT 1
        ),
        upd AS (
          UPDATE incidents i
             SET last_report_at = NOW()
            FROM cand
           WHERE i.id = cand.id
          RETURNING i.id
        )
        INSERT INTO incidents (kind, center, active, created_at, last_report_at)
        SELECT :kind, (SELECT g FROM me), true, NOW(), NOW()
        WHERE NOT EXISTS (SELECT 1 FROM upd)
        RETURNING id
    """)
    res = await db.execute(q, {"kind": kind, "lat": lat, "lng": lng})
    return res.scalar_one()

async def clear_nearest_incident(
    db: AsyncSession, kind: str, lat: float, lng: float
) -> Optional[str]:
    """
    Désactive l’incident actif le plus proche (≤ 800 m).
    """
    q = text("""
        WITH me AS (
          SELECT ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography AS g
        ),
        cand AS (
          SELECT id
            FROM incidents
           WHERE kind::text = :kind AND active=true   -- << cast text
             AND ST_DWithin(center, (SELECT g FROM me), CAST(800 AS double precision))
           ORDER BY center::geometry <-> (SELECT g::geometry FROM me)
           LIMIT 1
        )
        UPDATE incidents i
           SET active=false, cleared_at=NOW()
          FROM cand
         WHERE i.id = cand.id
        RETURNING i.id
    """)
    res = await db.execute(q, {"kind": kind, "lat": lat, "lng": lng})
    return res.scalar_one_or_none()


# --- Expirations automatiques ---------------------------------------------

async def expire_stale_outages(db: AsyncSession) -> None:
    """
    Ferme automatiquement les zones 'ongoing' s'il n'y a plus de 'cut'
    récent autour (fenêtre 45 min, marge 1.5x radius).
    """
    q = text("""
        UPDATE outages o
           SET status='restored',
               restored_at = COALESCE(o.restored_at, NOW())
         WHERE o.status='ongoing'
           AND NOT EXISTS (
                SELECT 1
                  FROM reports r
                 WHERE r.kind::text = o.kind::text         -- << cast text
                   AND r.signal::text = 'cut'              -- << cast text
                   AND r.created_at >= NOW() - INTERVAL '45 minutes'
                   AND ST_DWithin(r.geom::geography, o.center, (o.radius_m * 1.5)::double precision)
           )
    """)
    await db.execute(q)

async def expire_incidents(db: AsyncSession) -> None:
    """
    TTL auto : trafic 45 min, accident 3 h, feu 4 h, inondation 24 h.
    """
    q = text("""
        UPDATE incidents
           SET active=false, cleared_at=COALESCE(cleared_at, NOW())
         WHERE active=true
           AND (
                (kind::text='traffic'  AND NOW()-last_report_at > INTERVAL '45 minutes') OR
                (kind::text='accident' AND NOW()-last_report_at > INTERVAL '3 hours')  OR
                (kind::text='fire'     AND NOW()-last_report_at > INTERVAL '4 hours')  OR
                (kind::text='flood'    AND NOW()-last_report_at > INTERVAL '24 hours')
           )
    """)
    await db.execute(q)
