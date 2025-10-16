# app/routes/map.py
from fastapi import APIRouter, Depends, HTTPException, Query, Response, Request, Header
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from typing import Optional
from app.db import get_db
import os, uuid

router = APIRouter()

# --------- Config ----------
POINTS_WINDOW_MIN   = int(os.getenv("POINTS_WINDOW_MIN", "240"))
MAX_REPORTS         = int(os.getenv("MAX_REPORTS", "500"))
RESTORE_RADIUS_M    = int(os.getenv("RESTORE_RADIUS_M", "200"))
CLEANUP_RADIUS_M    = int(os.getenv("CLEANUP_RADIUS_M", "80"))
ADMIN_TOKEN         = (os.getenv("ADMIN_TOKEN") or os.getenv("NEXT_PUBLIC_ADMIN_TOKEN") or "").strip()

# Ownership: seul l’auteur du CUT proche (et récent) peut RESTORE
OWNERSHIP_RADIUS_M  = int(os.getenv("OWNERSHIP_RADIUS_M", "150"))     # rayon d’association
OWNERSHIP_WINDOW_MIN= int(os.getenv("OWNERSHIP_WINDOW_MIN", "1440"))  # 24h

def _check_admin_token(request: Request):
    if ADMIN_TOKEN:
        tok = request.headers.get("x-admin-token", "")
        if tok != ADMIN_TOKEN:
            raise HTTPException(status_code=401, detail="Invalid admin token")

def _to_uuid_or_none(v) -> Optional[str]:
    if not v:
        return None
    try:
        return str(uuid.UUID(str(v)))
    except Exception:
        return None

# --------- Helpers lecture ----------
async def fetch_outages(db: AsyncSession, lat: float, lng: float, r_m: float):
    q_full = text("""
        WITH me AS (SELECT ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography AS g)
        SELECT id, kind::text AS kind,
               CASE WHEN restored_at IS NULL THEN 'active' ELSE 'restored' END AS status,
               ST_Y(center::geometry) AS lat, ST_X(center::geometry) AS lng,
               started_at, restored_at
        FROM outages
        WHERE ST_DWithin(center, (SELECT g FROM me), :r)
        ORDER BY started_at DESC
    """)
    q_min = text("""
        WITH me AS (SELECT ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography AS g)
        SELECT id, kind::text AS kind, 'active' AS status,
               ST_Y(center::geometry) AS lat, ST_X(center::geometry) AS lng,
               NULL::timestamp AS started_at, NULL::timestamp AS restored_at
        FROM outages
        WHERE ST_DWithin(center, (SELECT g FROM me), :r)
        ORDER BY id DESC
    """)
    try:
        res = await db.execute(q_full, {"lng": lng, "lat": lat, "r": r_m})
    except Exception as e:
        if "UndefinedColumn" in str(e) or "does not exist" in str(e):
            await db.rollback()
            res = await db.execute(q_min, {"lng": lng, "lat": lat, "r": r_m})
        else:
            await db.rollback()
            raise
    rows = res.fetchall()
    return [
        {
            "id": r.id, "kind": r.kind, "status": r.status,
            "lat": float(r.lat), "lng": float(r.lng),
            "started_at": getattr(r, "started_at", None),
            "restored_at": getattr(r, "restored_at", None),
        } for r in rows
    ]

async def fetch_incidents(db: AsyncSession, lat: float, lng: float, r_m: float):
    q_full = text("""
        WITH me AS (SELECT ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography AS g)
        SELECT id, kind::text AS kind,
               CASE WHEN restored_at IS NULL THEN 'active' ELSE 'restored' END AS status,
               ST_Y(center::geometry) AS lat, ST_X(center::geometry) AS lng,
               started_at, restored_at
        FROM incidents
        WHERE ST_DWithin(center, (SELECT g FROM me), :r)
        ORDER BY started_at DESC
    """)
    q_min = text("""
        WITH me AS (SELECT ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography AS g)
        SELECT id, kind::text AS kind, 'active' AS status,
               ST_Y(center::geometry) AS lat, ST_X(center::geometry) AS lng,
               NULL::timestamp AS started_at, NULL::timestamp AS restored_at
        FROM incidents
        WHERE ST_DWithin(center, (SELECT g FROM me), :r)
        ORDER BY id DESC
    """)
    try:
        res = await db.execute(q_full, {"lng": lng, "lat": lat, "r": r_m})
    except Exception as e:
        if "UndefinedColumn" in str(e) or "does not exist" in str(e):
            await db.rollback()
            res = await db.execute(q_min, {"lng": lng, "lat": lat, "r": r_m})
        else:
            await db.rollback()
            raise
    rows = res.fetchall()
    return [
        {
            "id": r.id, "kind": r.kind, "status": r.status,
            "lat": float(r.lat), "lng": float(r.lng),
            "started_at": getattr(r, "started_at", None),
            "restored_at": getattr(r, "restored_at", None),
        } for r in rows
    ]

# --------- GET /map ----------
@router.get("/map")
async def map_endpoint(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    radius_km: float = Query(5.0, gt=0, le=50),
    response: Response = None,
    db: AsyncSession = Depends(get_db),
):
    try:
        try:
            await db.rollback()
        except Exception:
            pass

        r_m = float(radius_km * 1000.0)
        outages   = await fetch_outages(db, lat, lng, r_m)
        incidents = await fetch_incidents(db, lat, lng, r_m)

        # Derniers reports: SEULEMENT 'cut' récents
        q_rep = text(f"""
            WITH me AS (SELECT ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography AS g)
            SELECT id, kind::text AS kind, signal::text AS signal,
                   ST_Y(geom::geometry) AS lat, ST_X(geom::geometry) AS lng,
                   user_id, created_at
            FROM reports
            WHERE ST_DWithin(geom::geography, (SELECT g FROM me), :r)
              AND LOWER(TRIM(signal::text)) = 'cut'
              AND created_at > NOW() - INTERVAL '{POINTS_WINDOW_MIN} minutes'
            ORDER BY created_at DESC
            LIMIT :max
        """)
        res_rep = await db.execute(q_rep, {"lng": lng, "lat": lat, "r": r_m, "max": MAX_REPORTS})

        last_reports = [
            {
                "id": r.id, "kind": r.kind, "signal": r.signal,
                "lat": float(r.lat), "lng": float(r.lng),
                "user_id": r.user_id, "created_at": r.created_at,
            } for r in res_rep.fetchall()
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
        try:
            await db.rollback()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=str(e))

# --------- POST /report ----------
class ReportIn(BaseModel):
    kind: str            # "power" | "water" | "traffic" | "accident" | "fire" | "flood"
    signal: str          # "cut" | "restored"
    lat: float
    lng: float
    user_id: str | None = None

@router.post("/report")
async def post_report(
    p: ReportIn,
    db: AsyncSession = Depends(get_db),
    x_admin_token: Optional[str] = Header(default=None)
):
    """
    1) Insère le report (user_id -> UUID canonique ou NULL).
    2) Si signal='restored':
       - Autoriser seulement l’auteur du 'cut' récent et proche (sauf admin),
       - Marquer rétabli l’élément le + proche (incidents/outages),
       - Nettoyer les 'cut' proches.
    """
    try:
        sig = "restored" if str(p.signal).lower().strip() == "restored" else "cut"
        uid = _to_uuid_or_none(p.user_id)
        is_admin = (x_admin_token or "").strip() == ADMIN_TOKEN

        # ---- Ownership rule pour RESTORE (hors admin) ----
        if sig == "restored" and not is_admin:
            if not uid:
                raise HTTPException(status_code=403, detail="not_owner: missing user_id")
            check = await db.execute(text(f"""
                WITH me AS (SELECT ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography AS g)
                SELECT 1 FROM reports r
                WHERE r.kind = :kind
                  AND LOWER(TRIM(r.signal::text)) = 'cut'
                  AND r.user_id IS NOT DISTINCT FROM :uid
                  AND ST_DWithin(r.geom::geography, (SELECT g FROM me), :dr)
                  AND r.created_at > NOW() - INTERVAL '{OWNERSHIP_WINDOW_MIN} minutes'
                LIMIT 1
            """), {"kind": p.kind, "lng": p.lng, "lat": p.lat, "uid": uid, "dr": OWNERSHIP_RADIUS_M})
            if check.first() is None:
                raise HTTPException(status_code=403, detail="not_owner")

        # 1) Journaliser le report
        await db.execute(
            text("""
                INSERT INTO reports(kind, signal, geom, user_id, created_at)
                VALUES (:kind, :signal,
                        ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography,
                        :user_id, NOW())
            """),
            {"kind": p.kind, "signal": sig, "lat": p.lat, "lng": p.lng, "user_id": uid}
        )

        if sig == "restored":
            # 2a) Restaurer l’élément le plus proche
            target = "outages" if p.kind in ("power", "water") else "incidents"
            await db.execute(text(f"ALTER TABLE {target} ADD COLUMN IF NOT EXISTS restored_at timestamp NULL"))
            res_nearest = await db.execute(
                text(f"""
                    WITH me AS (SELECT ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography AS g)
                    SELECT id FROM {target}
                    WHERE kind = :kind AND (restored_at IS NULL OR restored_at > NOW() - INTERVAL '100 years')
                    ORDER BY center <-> (SELECT g FROM me)
                    LIMIT 1
                """), {"lng": p.lng, "lat": p.lat, "kind": p.kind}
            )
            row = res_nearest.first()
            if row and row[0] is not None:
                await db.execute(text(f"UPDATE {target} SET restored_at = NOW() WHERE id = :id"), {"id": row[0]})
            else:
                await db.execute(
                    text(f"""
                        WITH me AS (SELECT ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography AS g)
                        UPDATE {target} SET restored_at = NOW()
                        WHERE kind = :kind AND ST_DWithin(center, (SELECT g FROM me), :r)
                    """), {"lng": p.lng, "lat": p.lat, "kind": p.kind, "r": max(RESTORE_RADIUS_M, 1000)}
                )

            # 2b) Nettoyer les 'cut' proches (même user d’abord)
            del_same_user = await db.execute(
                text("""
                    WITH me AS (SELECT ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography AS g)
                    DELETE FROM reports r
                    WHERE LOWER(TRIM(r.signal::text))='cut'
                      AND r.kind = :kind
                      AND ST_DWithin(r.geom::geography, (SELECT g FROM me), :dr)
                      AND (r.user_id IS NOT DISTINCT FROM :uid)
                    RETURNING id
                """), {"lng": p.lng, "lat": p.lat, "kind": p.kind, "dr": CLEANUP_RADIUS_M, "uid": uid}
            )
            if len(del_same_user.fetchall()) == 0:
                await db.execute(
                    text("""
                        WITH me AS (SELECT ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography AS g)
                        DELETE FROM reports r
                        WHERE LOWER(TRIM(r.signal::text))='cut'
                          AND r.kind = :kind
                          AND ST_DWithin(r.geom::geography, (SELECT g FROM me), :dr)
                    """), {"lng": p.lng, "lat": p.lat, "kind": p.kind, "dr": CLEANUP_RADIUS_M}
                )

        await db.commit()
        return {"ok": True}

    except HTTPException:
        raise
    except Exception as e:
        try:
            await db.rollback()
        except:
            pass
        raise HTTPException(status_code=500, detail=f"report failed: {e}")

# --------- POST /reset_user ----------
@router.post("/reset_user")
async def reset_user(id: str = Query(..., alias="id"), db: AsyncSession = Depends(get_db)):
    try:
        try:
            await db.execute(text("DELETE FROM reports WHERE user_id = :id"), {"id": id})
        except Exception:
            await db.execute(text("DELETE FROM reports WHERE user_id = :id::uuid"), {"id": id})
        await db.commit()
        return {"ok": True}
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"reset_user failed: {e}")

# --------- ADMIN maintenance ----------
@router.post("/admin/wipe_all")
async def admin_wipe_all(request: Request, truncate: bool = Query(False), db: AsyncSession = Depends(get_db)):
    _check_admin_token(request)
    try:
        if truncate:
            await db.execute(text("TRUNCATE TABLE reports RESTART IDENTITY CASCADE"))
            await db.execute(text("TRUNCATE TABLE incidents RESTART IDENTITY CASCADE"))
            await db.execute(text("TRUNCATE TABLE outages RESTART IDENTITY CASCADE"))
        else:
            await db.execute(text("DELETE FROM reports"))
            await db.execute(text("DELETE FROM incidents"))
            await db.execute(text("DELETE FROM outages"))
        await db.commit()
        return {"ok": True}
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"wipe_all failed: {e}")

@router.post("/admin/ensure_schema")
async def admin_ensure_schema(db: AsyncSession = Depends(get_db)):
    try:
        await db.execute(text("ALTER TABLE incidents ADD COLUMN IF NOT EXISTS restored_at timestamp NULL"))
        await db.execute(text("ALTER TABLE outages   ADD COLUMN IF NOT EXISTS restored_at timestamp NULL"))
        await db.execute(text("CREATE INDEX IF NOT EXISTS idx_incidents_center ON incidents USING GIST ((center::geometry))"))
        await db.execute(text("CREATE INDEX IF NOT EXISTS idx_outages_center   ON outages   USING GIST ((center::geometry))"))
        await db.execute(text("CREATE INDEX IF NOT EXISTS idx_incidents_kind ON incidents(kind)"))
        await db.execute(text("CREATE INDEX IF NOT EXISTS idx_outages_kind   ON outages(kind)"))
        await db.commit()
        return {"ok": True}
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"ensure_schema failed: {e}")

@router.post("/admin/normalize_reports")
async def admin_normalize_reports(db: AsyncSession = Depends(get_db)):
    try:
        await db.execute(text("UPDATE reports SET signal='cut' WHERE LOWER(TRIM(signal::text)) IN ('down','cut')"))
        await db.execute(text("UPDATE reports SET signal='restored' WHERE LOWER(TRIM(signal::text)) IN ('up','restored')"))
        await db.execute(text("DELETE FROM reports WHERE LOWER(TRIM(signal::text))='restored'"))
        await db.commit()
        return {"ok": True}
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"normalize_reports failed: {e}")

class AdminCreateIn(BaseModel):
    kind: str
    lat: float
    lng: float
    started_at: Optional[str] = None

class AdminNearIn(BaseModel):
    kind: str
    lat: float
    lng: float
    radius_m: int = RESTORE_RADIUS_M

@router.post("/admin/seed_incident")
async def admin_seed_incident(p: AdminCreateIn, db: AsyncSession = Depends(get_db)):
    try:
        await db.execute(
            text("""
                INSERT INTO incidents(kind, center, started_at, restored_at)
                VALUES (:kind, ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography,
                        COALESCE(CAST(:started_at AS timestamp), NOW()), NULL)
            """),
            {"kind": p.kind, "lat": p.lat, "lng": p.lng, "started_at": p.started_at}
        )
        await db.commit()
        return {"ok": True}
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"seed_incident failed: {e}")

@router.post("/admin/seed_outage")
async def admin_seed_outage(p: AdminCreateIn, db: AsyncSession = Depends(get_db)):
    try:
        await db.execute(
            text("""
                INSERT INTO outages(kind, center, started_at, restored_at)
                VALUES (:kind, ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography,
                        COALESCE(CAST(:started_at AS timestamp), NOW()), NULL)
            """),
            {"kind": p.kind, "lat": p.lat, "lng": p.lng, "started_at": p.started_at}
        )
        await db.commit()
        return {"ok": True}
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"seed_outage failed: {e}")

@router.post("/admin/restore_near")
async def admin_restore_near(p: AdminNearIn, db: AsyncSession = Depends(get_db)):
    try:
        table = "outages" if p.kind in ("power", "water") else "incidents"
        await db.execute(
            text(f"""
                WITH me AS (SELECT ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography AS g)
                UPDATE {table} SET restored_at = NOW()
                WHERE kind = :kind AND ST_DWithin(center, (SELECT g FROM me), :r)
            """), {"kind": p.kind, "lat": p.lat, "lng": p.lng, "r": p.radius_m}
        )
        await db.commit()
        return {"ok": True}
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"restore_near failed: {e}")

@router.post("/admin/unrestore_near")
async def admin_unrestore_near(p: AdminNearIn, db: AsyncSession = Depends(get_db)):
    try:
        table = "outages" if p.kind in ("power", "water") else "incidents"
        await db.execute(
            text(f"""
                WITH me AS (SELECT ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography AS g)
                UPDATE {table} SET restored_at = NULL
                WHERE kind = :kind AND ST_DWithin(center, (SELECT g FROM me), :r)
            """), {"kind": p.kind, "lat": p.lat, "lng": p.lng, "r": p.radius_m}
        )
        await db.commit()
        return {"ok": True}
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"unrestore_near failed: {e}")

@router.post("/admin/delete_near")
async def admin_delete_near(p: AdminNearIn, db: AsyncSession = Depends(get_db)):
    try:
        table = "outages" if p.kind in ("power", "water") else "incidents"
        await db.execute(
            text(f"""
                WITH me AS (SELECT ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography AS g)
                DELETE FROM {table}
                WHERE kind = :kind AND ST_DWithin(center, (SELECT g FROM me), :r)
            """), {"kind": p.kind, "lat": p.lat, "lng": p.lng, "r": p.radius_m}
        )
        await db.commit()
        return {"ok": True}
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"delete_near failed: {e}")

@router.post("/admin/clear_restored_reports")
async def admin_clear_restored_reports(db: AsyncSession = Depends(get_db)):
    try:
        await db.execute(text("DELETE FROM reports WHERE LOWER(TRIM(signal::text))='restored'"))
        await db.commit()
        return {"ok": True}
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"clear_restored_reports failed: {e}")

@router.post("/admin/purge_old_reports")
async def admin_purge_old_reports(days: int = Query(7, ge=1, le=365), db: AsyncSession = Depends(get_db)):
    try:
        await db.execute(text("DELETE FROM reports WHERE created_at < NOW() - (:d || ' days')::interval"), {"d": days})
        await db.commit()
        return {"ok": True}
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"purge_old_reports failed: {e}")

@router.post("/admin/delete_report")
async def admin_delete_report(id: int = Query(...), db: AsyncSession = Depends(get_db)):
    try:
        await db.execute(text("DELETE FROM reports WHERE id = :id"), {"id": id})
        await db.commit()
        return {"ok": True}
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"delete_report failed: {e}")

# --- CSV exports ---
from fastapi.responses import StreamingResponse
import io, csv
from datetime import datetime

def _is_admin_req(request: Request):
    # accepte soit l'en-tête, soit ?token=...
    hdr = request.headers.get("x-admin-token", "").strip()
    q = (request.query_params.get("token") or "").strip()
    tok = ADMIN_TOKEN
    return bool(tok) and (hdr == tok or q == tok)

def _parse_dt(s: str | None):
    if not s: return None
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            pass
    return None

def _bbox_clause(min_lat, max_lat, min_lng, max_lng, alias="geom"):
    # alias = 'geom' (reports) ou 'center' (incidents/outages)
    parts = []
    params = {}
    try:
        if min_lat is not None: params["min_lat"] = float(min_lat)
        if max_lat is not None: params["max_lat"] = float(max_lat)
        if min_lng is not None: params["min_lng"] = float(min_lng)
        if max_lng is not None: params["max_lng"] = float(max_lng)
    except Exception:
        params = {}
    if len(params) == 4:
        parts.append(f"ST_Y({alias}::geometry) BETWEEN :min_lat AND :max_lat")
        parts.append(f"ST_X({alias}::geometry) BETWEEN :min_lng AND :max_lng")
    return (" AND ".join(parts), params)

@router.get("/admin/export_reports.csv")
async def admin_export_reports_csv(
    request: Request,
    date_from: str | None = None,
    date_to: str | None = None,
    kind: str | None = None,          # 'traffic'|'accident'|'fire'|'flood'|'power'|'water'
    signal: str | None = None,        # 'cut'|'restored'
    min_lat: float | None = None, max_lat: float | None = None,
    min_lng: float | None = None, max_lng: float | None = None,
    db: AsyncSession = Depends(get_db),
):
    if not _is_admin_req(request):
        raise HTTPException(status_code=401, detail="invalid admin token")

    dt_from = _parse_dt(date_from)
    dt_to   = _parse_dt(date_to)

    where = ["1=1"]
    params = {}
    if dt_from:
        where.append("created_at >= :df")
        params["df"] = dt_from
    if dt_to:
        where.append("created_at <= :dt")
        params["dt"] = dt_to
    if kind:
        where.append("kind = :kind")
        params["kind"] = kind
    if signal:
        where.append("LOWER(TRIM(signal::text)) = :sig")
        params["sig"] = signal.strip().lower()
    bbox_sql, bbox_params = _bbox_clause(min_lat, max_lat, min_lng, max_lng, alias="geom")
    if bbox_sql:
        where.append(bbox_sql)
        params.update(bbox_params)

    q = text(f"""
        SELECT id,
               kind::text AS kind,
               signal::text AS signal,
               ST_Y(geom::geometry) AS lat,
               ST_X(geom::geometry) AS lng,
               user_id,
               created_at
        FROM reports
        WHERE {" AND ".join(where)}
        ORDER BY created_at DESC, id DESC
        LIMIT 200000
    """)
    res = await db.execute(q, params)
    rows = res.fetchall()

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id","kind","signal","lat","lng","user_id","created_at"])
    for r in rows:
        w.writerow([r.id, r.kind, r.signal, float(r.lat), float(r.lng), r.user_id, r.created_at.isoformat() if r.created_at else ""])
    buf.seek(0)
    return StreamingResponse(buf, media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=reports.csv"})

@router.get("/admin/export_events.csv")
async def admin_export_events_csv(
    request: Request,
    date_from: str | None = None,
    date_to: str | None = None,
    kind: str | None = None,          # même valeurs
    status: str | None = None,        # 'active'|'restored'
    table: str | None = None,         # 'incidents'|'outages'|'both' (par défaut both)
    min_lat: float | None = None, max_lat: float | None = None,
    min_lng: float | None = None, max_lng: float | None = None,
    db: AsyncSession = Depends(get_db),
):
    if not _is_admin_req(request):
        raise HTTPException(status_code=401, detail="invalid admin token")

    dt_from = _parse_dt(date_from)
    dt_to   = _parse_dt(date_to)

    def _build_sql(tab):
        where = ["1=1"]
        params = {}
        if dt_from:
            where.append("started_at >= :df")
            params["df"] = dt_from
        if dt_to:
            where.append("started_at <= :dt")
            params["dt"] = dt_to
        if kind:
            where.append("kind = :kind")
            params["kind"] = kind
        if status in ("active","restored"):
            if status == "active":
                where.append("restored_at IS NULL")
            else:
                where.append("restored_at IS NOT NULL")
        bbox_sql, bbox_params = _bbox_clause(min_lat, max_lat, min_lng, max_lng, alias="center")
        if bbox_sql:
            where.append(bbox_sql)
            params.update(bbox_params)
        sql = text(f"""
            SELECT '{tab}' AS table_name,
                   id,
                   kind::text AS kind,
                   CASE WHEN restored_at IS NULL THEN 'active' ELSE 'restored' END AS status,
                   ST_Y(center::geometry) AS lat,
                   ST_X(center::geometry) AS lng,
                   started_at,
                   restored_at
            FROM {tab}
            WHERE {" AND ".join(where)}
        """)
        return sql, params

    tabs = ["incidents","outages"] if table in (None,"both","") else [table]
    all_rows = []
    for tname in tabs:
        sql, par = _build_sql(tname)
        res = await db.execute(sql, par)
        all_rows.extend([("incidents" if tname=="incidents" else "outages",) + tuple(r) for r in res.fetchall()])  # not used directly

    # all_rows currently holds tuples prefixed; rebuild properly:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["table","id","kind","status","lat","lng","started_at","restored_at","duration_min"])
    # requery for consistency (clearer):
    for tname in tabs:
        sql, par = _build_sql(tname)
        res = await db.execute(sql, par)
        for r in res.fetchall():
            started = r.started_at
            restored = r.restored_at
            dur_min = ""
            if started and restored:
                dur_min = int((restored - started).total_seconds() // 60)
            w.writerow([
                tname, r.id, r.kind, r.status,
                float(r.lat), float(r.lng),
                started.isoformat() if started else "",
                restored.isoformat() if restored else "",
                dur_min
            ])
    buf.seek(0)
    return StreamingResponse(buf, media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=events.csv"})

# --- GeoJSON & Aggregations ---
from fastapi.responses import StreamingResponse
import io, json
from datetime import datetime

@router.get("/admin/export_reports.geojson")
async def admin_export_reports_geojson(
    request: Request,
    date_from: str | None = None,
    date_to: str | None = None,
    kind: str | None = None,          # 'traffic'|'accident'|'fire'|'flood'|'power'|'water'
    signal: str | None = None,        # 'cut'|'restored'
    min_lat: float | None = None, max_lat: float | None = None,
    min_lng: float | None = None, max_lng: float | None = None,
    limit: int = 200000,
    db: AsyncSession = Depends(get_db),
):
    if not _is_admin_req(request):
        raise HTTPException(status_code=401, detail="invalid admin token")

    dt_from = _parse_dt(date_from)
    dt_to   = _parse_dt(date_to)

    where = ["1=1"]
    params = {}
    if dt_from:
        where.append("created_at >= :df"); params["df"] = dt_from
    if dt_to:
        where.append("created_at <= :dt"); params["dt"] = dt_to
    if kind:
        where.append("kind = :kind"); params["kind"] = kind
    if signal:
        where.append("LOWER(TRIM(signal::text)) = :sig"); params["sig"] = signal.strip().lower()
    bbox_sql, bbox_params = _bbox_clause(min_lat, max_lat, min_lng, max_lng, alias="geom")
    if bbox_sql: where.append(bbox_sql); params.update(bbox_params)

    q = text(f"""
        SELECT
          id,
          kind::text AS kind,
          signal::text AS signal,
          ST_AsGeoJSON(geom::geometry)::text AS geom_json,
          user_id,
          created_at
        FROM reports
        WHERE {" AND ".join(where)}
        ORDER BY created_at DESC, id DESC
        LIMIT :lim
    """)
    params["lim"] = limit
    res = await db.execute(q, params)
    rows = res.fetchall()

    fc = {
        "type": "FeatureCollection",
        "features": []
    }
    for r in rows:
        try:
            geom = json.loads(r.geom_json)
        except Exception:
            continue
        fc["features"].append({
            "type": "Feature",
            "geometry": geom,
            "properties": {
                "id": r.id,
                "kind": r.kind,
                "signal": r.signal,
                "user_id": r.user_id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
        })
    buf = io.StringIO()
    json.dump(fc, buf, ensure_ascii=False)
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/geo+json",
        headers={"Content-Disposition": "attachment; filename=reports.geojson"})


@router.get("/admin/export_events.geojson")
async def admin_export_events_geojson(
    request: Request,
    table: str | None = None,         # 'incidents'|'outages'|'both' (def both)
    date_from: str | None = None,
    date_to: str | None = None,
    kind: str | None = None,
    status: str | None = None,        # 'active'|'restored'
    min_lat: float | None = None, max_lat: float | None = None,
    min_lng: float | None = None, max_lng: float | None = None,
    limit: int = 200000,
    db: AsyncSession = Depends(get_db),
):
    if not _is_admin_req(request):
        raise HTTPException(status_code=401, detail="invalid admin token")

    dt_from = _parse_dt(date_from)
    dt_to   = _parse_dt(date_to)

    tabs = ["incidents","outages"] if table in (None,"both","") else [table]
    feats = []

    for tname in tabs:
        where = ["1=1"]
        params = {}
        if dt_from:
            where.append("started_at >= :df"); params["df"] = dt_from
        if dt_to:
            where.append("started_at <= :dt"); params["dt"] = dt_to
        if kind:
            where.append("kind = :kind"); params["kind"] = kind
        if status in ("active","restored"):
            if status == "active":
                where.append("restored_at IS NULL")
            else:
                where.append("restored_at IS NOT NULL")
        bbox_sql, bbox_params = _bbox_clause(min_lat, max_lat, min_lng, max_lng, alias="center")
        if bbox_sql: where.append(bbox_sql); params.update(bbox_params)

        sql = text(f"""
            SELECT
              id,
              kind::text AS kind,
              CASE WHEN restored_at IS NULL THEN 'active' ELSE 'restored' END AS status,
              ST_AsGeoJSON(center::geometry)::text AS geom_json,
              started_at, restored_at
            FROM {tname}
            WHERE {" AND ".join(where)}
            ORDER BY started_at DESC NULLS LAST, id DESC
            LIMIT :lim
        """)
        params["lim"] = limit
        res = await db.execute(sql, params)
        rows = res.fetchall()
        for r in rows:
            try:
                geom = json.loads(r.geom_json)
            except Exception:
                continue
            feats.append({
                "type": "Feature",
                "geometry": geom,
                "properties": {
                    "table": tname,
                    "id": r.id,
                    "kind": r.kind,
                    "status": r.status,
                    "started_at": r.started_at.isoformat() if r.started_at else None,
                    "restored_at": r.restored_at.isoformat() if r.restored_at else None,
                }
            })

    fc = {"type":"FeatureCollection","features":feats}
    buf = io.StringIO()
    json.dump(fc, buf, ensure_ascii=False)
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/geo+json",
        headers={"Content-Disposition": "attachment; filename=events.geojson"})


@router.get("/admin/export_aggregated.csv")
async def admin_export_aggregated_csv(
    request: Request,
    subject: str = "reports",         # 'reports' | 'events'
    by: str = "day_kind",             # 'day' | 'kind' | 'day_kind' | 'day_kind_status'
    table: str | None = None,         # pour events: 'incidents'|'outages'|'both'
    status: str | None = None,        # pour events: 'active'|'restored'
    date_from: str | None = None,
    date_to: str | None = None,
    kind: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    if not _is_admin_req(request):
        raise HTTPException(status_code=401, detail="invalid admin token")

    dt_from = _parse_dt(date_from)
    dt_to   = _parse_dt(date_to)

    buf = io.StringIO()
    w = csv.writer(buf)

    if subject == "reports":
        where = ["1=1"]; params = {}
        if dt_from: where.append("created_at >= :df"); params["df"] = dt_from
        if dt_to:   where.append("created_at <= :dt"); params["dt"] = dt_to
        if kind:    where.append("kind = :kind");       params["kind"] = kind

        if by == "day":
            sql = text(f"""
                SELECT date_trunc('day', created_at)::date AS day, COUNT(*) AS n
                FROM reports
                WHERE {" AND ".join(where)}
                GROUP BY 1 ORDER BY 1
            """)
            w.writerow(["day","reports"])
        elif by == "kind":
            sql = text(f"""
                SELECT kind::text AS kind, COUNT(*) AS n
                FROM reports
                WHERE {" AND ".join(where)}
                GROUP BY 1 ORDER BY 1
            """)
            w.writerow(["kind","reports"])
        else:  # day_kind
            sql = text(f"""
                SELECT date_trunc('day', created_at)::date AS day, kind::text AS kind, COUNT(*) AS n
                FROM reports
                WHERE {" AND ".join(where)}
                GROUP BY 1,2 ORDER BY 1,2
            """)
            w.writerow(["day","kind","reports"])

        res = await db.execute(sql, params)
        for r in res.fetchall():
            w.writerow(list(r))

    else:  # events
        tabs = ["incidents","outages"] if table in (None,"both","") else [table]
        # on agrège en UNION ALL puis regroupement Python (plus simple)
        rows = []
        for tname in tabs:
            where = ["1=1"]; params = {}
            if dt_from: where.append("started_at >= :df"); params["df"] = dt_from
            if dt_to:   where.append("started_at <= :dt"); params["dt"] = dt_to
            if kind:    where.append("kind = :kind");       params["kind"] = kind
            if status in ("active","restored"):
                if status == "active": where.append("restored_at IS NULL")
                else: where.append("restored_at IS NOT NULL")

            sql = text(f"""
                SELECT
                  date_trunc('day', started_at)::date AS day,
                  kind::text AS kind,
                  CASE WHEN restored_at IS NULL THEN 'active' ELSE 'restored' END AS status,
                  started_at, restored_at
                FROM {tname}
                WHERE {" AND ".join(where)}
            """)
            res = await db.execute(sql, params)
            rows.extend(res.fetchall())

        # regroupement
        from collections import defaultdict
        agg = defaultdict(lambda: {"n":0, "dur_sum":0.0, "dur_min":None, "dur_max":None})
        for r in rows:
            day = r.day
            kindv = r.kind
            statusv = r.status
            key = None
            if by == "day":
                key = (str(day),)
            elif by == "kind":
                key = (kindv,)
            elif by == "day_kind":
                key = (str(day), kindv)
            else:  # day_kind_status
                key = (str(day), kindv, statusv)
            agg[key]["n"] += 1
            if r.started_at and r.restored_at:
                dur = (r.restored_at - r.started_at).total_seconds() / 60.0
                agg[key]["dur_sum"] += dur
                agg[key]["dur_min"] = dur if agg[key]["dur_min"] is None else min(agg[key]["dur_min"], dur)
                agg[key]["dur_max"] = dur if agg[key]["dur_max"] is None else max(agg[key]["dur_max"], dur)

        # header & rows
        if by == "day":
            w.writerow(["day","events","avg_duration_min","min_duration_min","max_duration_min"])
        elif by == "kind":
            w.writerow(["kind","events","avg_duration_min","min_duration_min","max_duration_min"])
        elif by == "day_kind":
            w.writerow(["day","kind","events","avg_duration_min","min_duration_min","max_duration_min"])
        else:
            w.writerow(["day","kind","status","events","avg_duration_min","min_duration_min","max_duration_min"])

        for key, val in sorted(agg.items()):
            avg = ""
            if val["dur_sum"] > 0 and val["n"] > 0:
                # moyenne sur les éléments avec durée (approx via dur_sum / n ; ok si peu de non-restored)
                avg = round(val["dur_sum"] / val["n"], 2)
            row = list(key) + [val["n"], avg,
                               round(val["dur_min"],2) if val["dur_min"] is not None else "",
                               round(val["dur_max"],2) if val["dur_max"] is not None else ""]
            w.writerow(row)

    buf.seek(0)
    return StreamingResponse(buf, media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=aggregated.csv"})
