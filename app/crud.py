# app/crud.py
from __future__ import annotations

from typing import Any, Dict, Optional
import os

from sqlalchemy import text, bindparam
from sqlalchemy.types import Float
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import UUID

# -----------------------------------------------------------------------------
# Config / Logs
# -----------------------------------------------------------------------------
LOG_AGG = (os.getenv("LOG_AGG", "0") != "0")   # LOG_AGG=1 pour activer

# Rayon d’acceptation “fermeture tolérante” d’une zone par clic “rétabli”
CLOSE_SEARCH_METERS = 3000.0
CLOSE_FACTOR       = 1.5     # on accepte si dist <= 1.5 * radius
CLOSE_HARDCAP      = 1500.0  # ou si dist <= 1500 m

# Rayon de fusion des incidents (report 'cut' -> incident) : 300 m
INCIDENT_MERGE_METERS = 300.0

# TTL incidents (si aucun nouveau report ‘cut’ n’arrive sur eux)
TTL_TRAFFIC_MIN  = int(os.getenv("TTL_TRAFFIC_MIN",  "45"))
TTL_ACCIDENT_H   = int(os.getenv("TTL_ACCIDENT_H",   "3"))
TTL_FIRE_H       = int(os.getenv("TTL_FIRE_H",       "4"))
TTL_FLOOD_H      = int(os.getenv("TTL_FLOOD_H",     "24"))

# -----------------------------------------------------------------------------
# Introspection des types (pour gérer enums ou text dynamiquement)
# -----------------------------------------------------------------------------
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

# -----------------------------------------------------------------------------
# Constantes
# -----------------------------------------------------------------------------
KINDS_OUTAGE    = {"power", "water"}
INCIDENT_KINDS  = {"traffic", "accident", "fire", "flood"}

# -----------------------------------------------------------------------------
# INSERT Report (+ actions automatiques)
# -----------------------------------------------------------------------------
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
    Insère un report et déclenche les actions auto indispensables :
      - power/water + restored -> ferme la zone la plus proche (si dans le cône)
      - traffic/accident/fire/flood + cut -> upsert incident (fusion à 300 m)
      - traffic/accident/fire/flood + restored -> clear incident le plus proche (≤ 800 m)
    """

    # 0) S’assurer que la FK user existe si user_id fourni
    if user_id:
        try:
            await db.execute(
                text("INSERT INTO app_users (id) VALUES (CAST(:uid AS uuid)) ON CONFLICT (id) DO NOTHING"),
                {"uid": user_id},
            )
            await db.commit()
        except Exception:
            await db.rollback()

    # 1) Introspection (enum/text) pour kind/signal
    kind_typ = await get_column_typename(db, "reports", "kind")
    sig_typ  = await get_column_typename(db, "reports", "signal")
    kind_is_enum = await is_enum_typename(db, kind_typ)
    sig_is_enum  = await is_enum_typename(db, sig_typ)

    kind_cast = kind_typ if kind_is_enum else "text"
    sig_cast  = sig_typ  if sig_is_enum  else "text"

    # 2) Insert
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
    """).bindparams(bindparam("user_id", type_=UUID(as_uuid=False)))

    try:
        res = await db.execute(insert_sql, {
            "kind": kind, "signal": signal, "lat": lat, "lng": lng,
            "accuracy_m": accuracy_m, "note": note, "photo_url": photo_url,
            "user_id": user_id
        })
        report_id = res.scalar_one()
        await db.commit()
        if LOG_AGG:
            print(f"[report] inserted id={report_id} kind={kind} signal={signal} lat={lat} lng={lng}")
    except Exception:
        await db.rollback()
        raise

    # 3) Actions auto
    try:
        if signal == "restored" and kind in KINDS_OUTAGE:
            closed = await close_nearest_outage_on_restored(db, kind, lat, lng)
            if LOG_AGG and closed:
                print(f"[outage] restored by user click -> id={closed}")

        if signal == "cut" and kind in INCIDENT_KINDS:
            iid = await upsert_incident_from_report(db, kind, lat, lng)
            if LOG_AGG:
                print(f"[incident] upsert kind={kind} -> id={iid}")

        if signal == "restored" and kind in INCIDENT_KINDS:
            cleared = await clear_nearest_incident(db, kind, lat, lng)
            if LOG_AGG and cleared:
                print(f"[incident] cleared kind={kind} -> id={cleared}")

        await db.commit()
    except Exception as e:
        await db.rollback()
        if LOG_AGG:
            print(f"[report-actions] error: {e}")

    return report_id

# -----------------------------------------------------------------------------
# /map : lecture
# -----------------------------------------------------------------------------
async def get_outages_in_radius(
    db: AsyncSession, lat: float, lng: float, radius_km: float
) -> Dict[str, Any]:
    meters = float(radius_km * 1000.0)

    # OUTAGES (ongoing/restored)
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
        WHERE ST_DWithin(center, (SELECT g FROM me), CAST(:meters AS double precision) + radius_m)
        ORDER BY (status='ongoing') DESC, started_at DESC
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

    # INCIDENTS actifs seulement (évite les “fantômes”)
    q_inc = text("""
        WITH me AS (
          SELECT ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography AS g
        )
        SELECT id, kind, active,
               ST_Y(center::geometry) AS lat,
               ST_X(center::geometry) AS lng,
               started_at, last_report_at, ended_at
          FROM incidents
         WHERE active = true
           AND ST_DWithin(center, (SELECT g FROM me), CAST(:meters AS double precision))
         ORDER BY started_at DESC
    """).bindparams(bindparam("meters", type_=Float))

    inc_res = await db.execute(q_inc, {"lat": lat, "lng": lng, "meters": meters})
    incidents = [
        {
            "id": r.id,
            "kind": r.kind,
            "active": r.active,
            "center": {"lat": float(r.lat), "lng": float(r.lng)},
            "started_at": r.started_at,
            "last_report_at": r.last_report_at,
            "ended_at": r.ended_at,
        }
        for r in inc_res.fetchall()
    ]

    # Derniers reports (pins)
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
        WHERE ST_DWithin(geom, (SELECT g FROM me), CAST(:meters AS double precision))
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

    return {"outages": outages, "last_reports": last_reports, "incidents": incidents}

# -----------------------------------------------------------------------------
# Fermeture tolérante d’une zone par “restored”
# -----------------------------------------------------------------------------
async def close_nearest_outage_on_restored(
    db: AsyncSession, kind: str, lat: float, lng: float
) -> Optional[str]:
    q = text("""
        WITH me AS (
          SELECT ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography AS g
        ),
        cand AS (
          SELECT id, radius_m,
                 ST_Distance(center, (SELECT g FROM me)) AS dist
            FROM outages
           WHERE kind::text = :kind AND status='ongoing'
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

# -----------------------------------------------------------------------------
# Incidents : upsert/clear + TTL
# -----------------------------------------------------------------------------
async def upsert_incident_from_report(
    db: AsyncSession, kind: str, lat: float, lng: float
) -> str:
    """
    'cut' -> on fusionne à 300 m, sinon on crée un incident actif.
    Log : "[incident] merge->update id=..." ou "[incident] created id=..."
    """
    q = text("""
        WITH me AS (
          SELECT ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography AS g
        ),
        cand AS (
          SELECT id
            FROM incidents
           WHERE kind::text = :kind AND active=true
             AND ST_DWithin(center, (SELECT g FROM me), CAST(:merge_m AS double precision))
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
    """).bindparams(bindparam("merge_m", type_=Float))

    res = await db.execute(q, {"kind": kind, "lat": lat, "lng": lng, "merge_m": float(INCIDENT_MERGE_METERS)})
    row = res.scalar_one()
    # On ne sait pas si ça vient de upd ou insert (au niveau SQL), log “générique” :
    if LOG_AGG:
        print(f"[incident] upsert(kind={kind}) -> id={row} (merge<= {INCIDENT_MERGE_METERS}m)")
    return row

async def clear_nearest_incident(
    db: AsyncSession, kind: str, lat: float, lng: float
) -> Optional[str]:
    """
    'restored' -> désactive l’incident actif le plus proche (≤ 800 m).
    """
    q = text("""
        WITH me AS (
          SELECT ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography AS g
        ),
        cand AS (
          SELECT id
            FROM incidents
           WHERE kind::text = :kind AND active=true
             AND ST_DWithin(center, (SELECT g FROM me), CAST(800 AS double precision))
           ORDER BY center::geometry <-> (SELECT g::geometry FROM me)
           LIMIT 1
        )
        UPDATE incidents i
           SET active=false, ended_at=COALESCE(ended_at, NOW())
          FROM cand
         WHERE i.id = cand.id
        RETURNING i.id
    """)
    res = await db.execute(q, {"kind": kind, "lat": lat, "lng": lng})
    rid = res.scalar_one_or_none()
    if LOG_AGG and rid:
        print(f"[incident] cleared by user kind={kind} -> id={rid}")
    return rid

# -----------------------------------------------------------------------------
# Expirations automatiques
# -----------------------------------------------------------------------------
async def expire_stale_outages(db: AsyncSession) -> None:
    """
    Ferme automatiquement les zones 'ongoing' s'il n'y a plus de 'cut' récent
    autour (fenêtre 45 min, marge 1.5x radius).
    """
    q = text("""
        UPDATE outages o
           SET status='restored',
               restored_at = COALESCE(o.restored_at, NOW())
         WHERE o.status='ongoing'
           AND NOT EXISTS (
                SELECT 1
                  FROM reports r
                 WHERE r.kind::text = o.kind::text
                   AND r.signal::text = 'cut'
                   AND r.created_at >= NOW() - INTERVAL '45 minutes'
                   AND ST_DWithin(r.geom::geography, o.center, (o.radius_m * 1.5)::double precision)
           )
    """)
    res = await db.execute(q)
    if LOG_AGG:
        print(f"[agg] outages auto-closed: {res.rowcount or 0}")

async def expire_incidents(db: AsyncSession) -> None:
    """
    TTL auto : trafic 45 min, accident 3 h, feu 4 h, inondation 24 h.
    Désactive (active=false) et fixe ended_at si manquant.
    """
    q = text(f"""
        UPDATE incidents
           SET active=false, ended_at=COALESCE(ended_at, NOW())
         WHERE active=true
           AND (
                (kind::text='traffic'  AND NOW()-COALESCE(last_report_at, started_at) > INTERVAL '{TTL_TRAFFIC_MIN} minutes') OR
                (kind::text='accident' AND NOW()-COALESCE(last_report_at, started_at) > INTERVAL '{TTL_ACCIDENT_H} hours')  OR
                (kind::text='fire'     AND NOW()-COALESCE(last_report_at, started_at) > INTERVAL '{TTL_FIRE_H} hours')      OR
                (kind::text='flood'    AND NOW()-COALESCE(last_report_at, started_at) > INTERVAL '{TTL_FLOOD_H} hours')
           )
    """)
    res = await db.execute(q)
    if LOG_AGG:
        print(f"[agg] incidents expired: {res.rowcount or 0}")
