# app/routes/map.py
from fastapi import APIRouter, Depends, HTTPException, Query, Response, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from typing import Optional
from app.db import get_db
import os

router = APIRouter()

# --------- Config ----------
POINTS_WINDOW_MIN = int(os.getenv("POINTS_WINDOW_MIN", "240"))
MAX_REPORTS       = int(os.getenv("MAX_REPORTS", "500"))
RESTORE_RADIUS_M  = int(os.getenv("RESTORE_RADIUS_M", "200"))  # fallback large si besoin
ADMIN_TOKEN       = (os.getenv("ADMIN_TOKEN") or os.getenv("NEXT_PUBLIC_ADMIN_TOKEN") or "").strip()

def _check_admin_token(request: Request):
    if ADMIN_TOKEN:
        tok = request.headers.get("x-admin-token", "")
        if tok != ADMIN_TOKEN:
            raise HTTPException(status_code=401, detail="Invalid admin token")

# --------- Helpers lecture ----------
async def fetch_outages(db: AsyncSession, lat: float, lng: float, r_m: float):
    q_full = text("""
        WITH me AS (SELECT ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography AS g)
        SELECT id,
               kind::text AS kind,
               CASE WHEN restored_at IS NULL THEN 'active' ELSE 'restored' END AS status,
               ST_Y(center::geometry) AS lat,
               ST_X(center::geometry) AS lng,
               started_at, restored_at
        FROM outages
        WHERE ST_DWithin(center, (SELECT g FROM me), :r)
        ORDER BY started_at DESC
    """)
    q_min = text("""
        WITH me AS (SELECT ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography AS g)
        SELECT id,
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
        SELECT id,
               kind::text AS kind,
               CASE WHEN restored_at IS NULL THEN 'active' ELSE 'restored' END AS status,
               ST_Y(center::geometry) AS lat,
               ST_X(center::geometry) AS lng,
               started_at, restored_at
        FROM incidents
        WHERE ST_DWithin(center, (SELECT g FROM me), :r)
        ORDER BY started_at DESC
    """)
    q_min = text("""
        WITH me AS (SELECT ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography AS g)
        SELECT id,
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

        outages = await fetch_outages(db, lat, lng, r_m)
        incidents = await fetch_incidents(db, lat, lng, r_m)

        # Reports : n'afficher QUE les 'cut' (fini les valeurs legacy down / cut[espace] / etc.)
        q_rep = text(f"""
            WITH me AS (
              SELECT ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography AS g
            )
            SELECT
              id,
              kind::text AS kind,
              signal::text AS signal,
              ST_Y(geom::geometry) AS lat,
              ST_X(geom::geometry) AS lng,
              user_id,
              created_at
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
async def post_report(p: ReportIn, db: AsyncSession = Depends(get_db)):
    """
    1) Insère le report.
    2) Si signal='restored', marque comme rétabli l'élément le PLUS PROCHE (par id), sinon fallback rayon large.
    """
    try:
        sig = "restored" if str(p.signal).lower().strip() == "restored" else "cut"

        # 1) log report
        await db.execute(
            text("""
                INSERT INTO reports(kind, signal, geom, user_id, created_at)
                VALUES (:kind, :signal,
                        ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography,
                        :user_id, NOW())
            """),
            {"kind": p.kind, "signal": sig, "lat": p.lat, "lng": p.lng, "user_id": p.user_id}
        )

        # 2) restored => update nearest
        if sig == "restored":
            target_table = "outages" if p.kind in ("power", "water") else "incidents"
            # s'assurer que la colonne existe
            await db.execute(text(f"ALTER TABLE {target_table} ADD COLUMN IF NOT EXISTS restored_at timestamp NULL"))

            # chercher l'id le plus proche
            res_nearest = await db.execute(
                text(f"""
                    WITH me AS (
                      SELECT ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography AS g
                    )
                    SELECT id
                    FROM {target_table}
                    WHERE kind = :kind
                      AND (restored_at IS NULL OR restored_at > NOW() - INTERVAL '100 years')
                    ORDER BY center <-> (SELECT g FROM me)
                    LIMIT 1
                """),
                {"lng": p.lng, "lat": p.lat, "kind": p.kind}
            )
            row = res_nearest.first()

            if row and row[0] is not None:
                await db.execute(text(f"UPDATE {target_table} SET restored_at = NOW() WHERE id = :id"), {"id": row[0]})
            else:
                # fallback rayon large
                await db.execute(
                    text(f"""
                        WITH me AS (
                          SELECT ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography AS g
                        )
                        UPDATE {target_table}
                           SET restored_at = NOW()
                         WHERE kind = :kind
                           AND ST_DWithin(center, (SELECT g FROM me), :r)
                    """),
                    {"lng": p.lng, "lat": p.lat, "kind": p.kind, "r": max(RESTORE_RADIUS_M, 1000)}
                )

        await db.commit()
        return {"ok": True}

    except Exception as e:
        try:
            await db.rollback()
        except:
            pass
        raise HTTPException(status_code=500, detail=f"report failed: {e}")

# --------- POST /reset_user ----------
@router.post("/reset_user")
async def reset_user(id: str = Query(..., alias="id"), db: AsyncSession = Depends(get_db)):
    """
    Supprime tous les reports de cet utilisateur (UUID ou TEXT).
    Double tentative si la colonne est de type uuid.
    """
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

# --------- ADMIN: maintenance ----------
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

# --- Normalisation & ménage des reports (legacy) ---
@router.post("/admin/normalize_reports")
async def admin_normalize_reports(db: AsyncSession = Depends(get_db)):
    """
    Normalise les valeurs legacy du champ signal :
    - 'down' / 'cut ' -> 'cut'
    - 'up'  / 'restored ' -> 'restored'
    Puis supprime les reports 'restored' (non affichés sur la carte).
    """
    try:
        await db.execute(text("UPDATE reports SET signal='cut' WHERE LOWER(TRIM(signal::text)) IN ('down','cut')"))
        await db.execute(text("UPDATE reports SET signal='restored' WHERE LOWER(TRIM(signal::text)) IN ('up','restored')"))
        await db.execute(text("DELETE FROM reports WHERE LOWER(TRIM(signal::text))='restored'"))
        await db.commit()
        return {"ok": True}
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"normalize_reports failed: {e}")

# seed & ops proximité
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
                VALUES (
                  :kind,
                  ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography,
                  COALESCE(CAST(:started_at AS timestamp), NOW()),
                  NULL
                )
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
                VALUES (
                  :kind,
                  ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography,
                  COALESCE(CAST(:started_at AS timestamp), NOW()),
                  NULL
                )
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
            """),
            {"kind": p.kind, "lat": p.lat, "lng": p.lng, "r": p.radius_m}
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
            """),
            {"kind": p.kind, "lat": p.lat, "lng": p.lng, "r": p.radius_m}
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
            """),
            {"kind": p.kind, "lat": p.lat, "lng": p.lng, "r": p.radius_m}
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
