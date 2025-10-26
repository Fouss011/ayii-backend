# app/routes/admin_cta.py
import os
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Header, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

async def _supabase_sign_url(public_or_path: str, expires_sec: int = 120) -> str | None:
    """
    Transforme une URL publique Supabase ou un chemin <bucket>/<path> en URL signée courte.
    Retourne None si la signature est impossible (ex: clés manquantes).
    """
    supa_url = (os.getenv("SUPABASE_URL") or "").rstrip("/")
    supa_key = os.getenv("SUPABASE_SERVICE_ROLE") or os.getenv("SUPABASE_SERVICE_KEY")
    bucket = os.getenv("SUPABASE_BUCKET", "attachments")
    if not (supa_url and supa_key):
        return None

    # Déduire "<bucket>/<path>"
    if "/storage/v1/object/public/" in public_or_path:
        try:
            after = public_or_path.split("/storage/v1/object/public/")[1]
        except Exception:
            return None
    else:
        p = public_or_path.strip().lstrip("/")
        after = p if p.startswith(bucket + "/") else f"{bucket}/{p}"

    sign_endpoint = f"{supa_url}/storage/v1/object/sign/{after}"

    try:
        import httpx
        headers = {"Authorization": f"Bearer {supa_key}", "Content-Type": "application/json"}
        payload = {"expiresIn": int(expires_sec)}
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(sign_endpoint, headers=headers, json=payload)
        if r.status_code not in (200, 201):
            return None
        data = r.json()
        signedURL = data.get("signedURL") or data.get("signedUrl")
        if not signedURL:
            return None
        return f"{supa_url}/storage/v1/{signedURL}"
    except Exception:
        return None


# ✅ Import tolérant de get_db
try:
    from app.dependencies import get_db  # si présent
except Exception:
    try:
        from app.db import get_db        # fallback (cas courant chez toi)
    except Exception as e:
        raise RuntimeError("Impossible d'importer get_db (ni app.dependencies.get_db, ni app.db.get_db).") from e

ADMIN_TOKEN = (os.getenv("ADMIN_TOKEN") or os.getenv("NEXT_PUBLIC_ADMIN_TOKEN") or "").strip()
ATTACH_WINDOW_H = int(os.getenv("ATTACH_WINDOW_H", "48"))     # fenêtre temporelle des attachments
ATTACH_RADIUS_M = int(os.getenv("ATTACH_RADIUS_M", "120"))    # rayon de recherche autour d'un report
DEFAULT_LIMIT   = 100

router = APIRouter(prefix="/cta", tags=["cta"])


# ---------------------------------------------------------------------
# Auth très simple via x-admin-token
# ---------------------------------------------------------------------
def require_admin(token: Optional[str] = Header(None, alias="x-admin-token")) -> bool:
    if not ADMIN_TOKEN or not token or token.strip() != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return True


# ---------------------------------------------------------------------
# Helper SQL : build SELECT avec join LATERAL => photo_url depuis attachments
# ---------------------------------------------------------------------
def _build_query_with_attachment(filter_by_status: bool) -> str:
    """
    Si filter_by_status=True, inclut "AND r.status = :status" dans WHERE.
    Retourne un SELECT qui expose lat/lng, status, created_at, et la dernière photo proche.
    """
    where_status = "AND r.status = :status" if filter_by_status else ""
    q = f"""
        SELECT
            r.id,
            r.kind::text     AS kind,
            r.signal::text   AS signal,
            ST_Y(r.geom::geometry) AS lat,
            ST_X(r.geom::geometry) AS lng,
            r.created_at,
            r.status,
            att.url          AS photo_url
        FROM reports r
        LEFT JOIN LATERAL (
            SELECT a.url
            FROM attachments a
            WHERE a.kind::text = r.kind::text
              AND a.created_at > NOW() - INTERVAL '{ATTACH_WINDOW_H} hours'
              AND ST_DWithin(a.geom::geography, r.geom::geography, {ATTACH_RADIUS_M})
            ORDER BY a.created_at DESC
            LIMIT 1
        ) att ON TRUE
        WHERE 1=1
        {where_status}
        ORDER BY r.created_at DESC
        LIMIT :limit
    """
    return q


# ---------------------------------------------------------------------
# GET /cta/incidents
# Liste les reports avec dernière photo proche (si existante)
# ---------------------------------------------------------------------
@router.get("/incidents")
async def list_incidents(
    ok: bool = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    status: Optional[str] = Query(None, description="Filtrer par status 'new'|'confirmed'|'resolved'"),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=500),
):
    """
    Liste des incidents pour CTA avec photo éventuellement signée (URL courte).
    Utilise _build_query_with_attachment(filter_by_status=...) pour inclure une 'photo_url' par proximité.
    """
    from datetime import datetime, timezone
    params: Dict[str, Any] = {"limit": int(limit)}

    # 1) Récupération des lignes
    try:
        if status:
            params["status"] = status
            q = text(_build_query_with_attachment(filter_by_status=True))
        else:
            q = text(_build_query_with_attachment(filter_by_status=False))
        rows = (await db.execute(q, params)).mappings().all()
    except Exception:
        # fallback si la colonne status n'existe pas ou autre
        q = text(_build_query_with_attachment(filter_by_status=False))
        rows = (await db.execute(q, {"limit": int(limit)})).mappings().all()

    now = datetime.now(timezone.utc)

    # Helper: signe l'URL si _supabase_sign_url est dispo, sinon renvoie l'originale
    async def _maybe_sign(url: Optional[str]) -> Optional[str]:
        if not url:
            return url
        try:
            # _supabase_sign_url doit être définie (ou importée) ailleurs
            signed = await _supabase_sign_url(url, expires_sec=120)  # type: ignore[name-defined]
            return signed or url
        except Exception:
            return url

    # 2) Construction des items + signature C2 ici
    out: List[Dict[str, Any]] = []
    for r in rows:
        d = dict(r)

        # âge en minutes
        created = d.get("created_at")
        try:
            age_min = int((now - created).total_seconds() // 60) if created else None
        except Exception:
            age_min = None
        d["age_min"] = age_min

        # signature de la photo si présente
        photo = d.get("photo_url")
        d["photo_url"] = await _maybe_sign(photo)

        out.append(d)

    return {"items": out, "count": len(out)}

# ---------------------------------------------------------------------
# POST /cta/cleanup
# Nettoyage de vieux reports (utilise ton service si présent)
# ---------------------------------------------------------------------
@router.post("/cleanup")
async def do_cleanup(
    ok: bool = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    hours: int = Query(24, ge=1, le=24*31, description="Supprimer/archiver les reports plus vieux que N heures"),
):
    """
    Appelle app.services.cleanup.cleanup_old_reports si dispo.
    Sinon, fallback : suppression basique en SQL.
    """
    try:
        try:
            from app.services.cleanup import cleanup_old_reports
            n = await cleanup_old_reports(db, hours=hours)
            return {"deleted": n}
        except Exception:
            # Fallback : delete simple si le service n'existe pas
            q = text("DELETE FROM reports WHERE created_at < NOW() - (:h || ' hours')::interval")
            res = await db.execute(q, {"h": int(hours)})
            await db.commit()
            # rowcount peut être None selon driver; on renvoie au moins ok=true
            return {"ok": True, "deleted": getattr(res, "rowcount", None)}
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"cleanup error: {e}")
