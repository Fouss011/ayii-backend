# app/routes/map.py
# (optionnel) """Docstring module..."""

from __future__ import annotations  # ← doit être tout en haut

from fastapi import (
    APIRouter, Depends, HTTPException, Query, Response, Request, Header,
    UploadFile, File, Form, Body
)
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from typing import Optional, Any, List
from uuid import UUID
from datetime import datetime, timezone
import os, uuid, mimetypes, io, csv, json, time

from app.db import get_db
from app.config import BASE_PUBLIC_URL, STATIC_DIR, STATIC_URL_PATH  # constants only (no circular import)

router = APIRouter()

# Si Python < 3.10, dé-commente la ligne suivante et remplace l’annotation de _signed_cache plus bas
# from typing import Dict, Tuple

# ---- Supabase URL signer ----
import os
import httpx

async def _supabase_sign_url(public_or_path: str, expires_sec: int = 300) -> str | None:
    """
    Prend une URL publique Supabase OU juste un chemin, et renvoie une URL signée.
    Si Supabase n’est pas configuré → None.
    """
    supa_url = (os.getenv("SUPABASE_URL") or "").rstrip("/")
    supa_key = (
        os.getenv("SUPABASE_SERVICE_ROLE")
        or os.getenv("SUPABASE_SERVICE_KEY")
        or os.getenv("SUPABASE_ANON_KEY")
    )
    bucket = os.getenv("SUPABASE_BUCKET", "attachments")

    # si on n'a pas au moins l'URL et une clé → on ne signe pas
    if not supa_url or not supa_key:
      # tu peux logger ici si tu veux
      return None

    # normaliser le chemin à signer
    if "/storage/v1/object/public/" in public_or_path:
        # on a reçu une URL complète
        try:
            after = public_or_path.split("/storage/v1/object/public/")[1]
        except Exception:
            return None
    else:
        # on a reçu juste le chemin
        p = public_or_path.strip().lstrip("/")
        # on s'assure que ça commence par le bucket
        after = p if p.startswith(bucket + "/") else f"{bucket}/{p}"

    sign_endpoint = f"{supa_url}/storage/v1/object/sign/{after}"

    try:
        headers = {
            "Authorization": f"Bearer {supa_key}",
            "Content-Type": "application/json",
        }
        payload = {"expiresIn": int(expires_sec)}
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(sign_endpoint, headers=headers, json=payload)

        if r.status_code not in (200, 201):
            # ici pareil tu peux logger r.text
            return None

        data = r.json()
        signedURL = data.get("signedURL") or data.get("signedUrl")
        if not signedURL:
            return None

        # on reconstruit une URL complète
        return (f"{supa_url}/storage/v1/{signedURL}").replace(
            "/storage/v1//", "/storage/v1/"
        )
    except Exception:
        return None

# Si Python ≥ 3.10
_signed_cache: dict[str, tuple[float, str]] = {}  # url -> (expires_at, signed_url)
# Si Python < 3.10, utilise plutôt :
# _signed_cache: Dict[str, Tuple[float, str]] = {}

async def get_signed_cached(url: str, cache_ttl: int = 60, link_ttl_sec: int = 300) -> str | None:
    now = time.time()
    cached = _signed_cache.get(url)
    if cached and now < cached[0]:
        return cached[1]
    signed = await _supabase_sign_url(url, expires_sec=link_ttl_sec)
    if signed:
        _signed_cache[url] = (now + cache_ttl, signed)
    return signed


# --------- Config ----------
POINTS_WINDOW_MIN    = int(os.getenv("POINTS_WINDOW_MIN", "240"))
MAX_REPORTS          = int(os.getenv("MAX_REPORTS", "500"))
RESTORE_RADIUS_M     = int(os.getenv("RESTORE_RADIUS_M", "200"))
CLEANUP_RADIUS_M     = int(os.getenv("CLEANUP_RADIUS_M", "80"))
OWNERSHIP_RADIUS_M   = int(os.getenv("OWNERSHIP_RADIUS_M", "150"))
OWNERSHIP_WINDOW_MIN = int(os.getenv("OWNERSHIP_WINDOW_MIN", "1440"))  # 24h
ADMIN_TOKEN          = (os.getenv("ADMIN_TOKEN") or os.getenv("NEXT_PUBLIC_ADMIN_TOKEN") or "").strip()

# Pièces jointes + auto-expire
ATTACH_WINDOW_H      = int(os.getenv("ATTACH_WINDOW_H", "48"))  # photos visibles près d’un incident sur 48h
AUTO_EXPIRE_H        = int(os.getenv("AUTO_EXPIRE_H", "6"))     # auto-clôture à 6h

SUPABASE_URL         = (os.getenv("SUPABASE_URL") or "").rstrip("/")
SUPABASE_KEY         = os.getenv("SUPABASE_SERVICE_ROLE", "")
SUPABASE_BUCKET      = os.getenv("SUPABASE_BUCKET", "attachments")

ALERT_RADIUS_M   = int(os.getenv("ALERT_RADIUS_M", "100"))   # rayon des zones d'alerte (≈100m)
ALERT_WINDOW_H   = int(os.getenv("ALERT_WINDOW_H", "3"))     # fenêtre de temps pour les preuves (3h)
ALERT_THRESHOLD  = int(os.getenv("ALERT_THRESHOLD", "3"))    # nb min de signalements pour une zone
RESPONDER_TOKEN  = (os.getenv("RESPONDER_TOKEN") or "").strip()  # jeton simple pour “pompiers”

ALLOWED_KINDS = {
    "traffic","accident","fire","flood","power","water",
    "assault","weapon","medical"  # nouveaux types incidents
}
# --------- Helpers ----------
def _to_uuid_or_none(val: Optional[str]):
    try:
        if not val:
            return None
        return str(uuid.UUID(str(val)))
    except Exception:
        return None

def _check_admin_token(request: Request):
    if ADMIN_TOKEN:
        tok = request.headers.get("x-admin-token", "")
        if tok != ADMIN_TOKEN:
            raise HTTPException(status_code=401, detail="Invalid admin token")

def _now_isoz():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

# --------- Preflight CORS ----------
@router.options("/report")
async def options_report():
    resp = Response(status_code=204)
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, x-admin-token"
    resp.headers["Vary"] = "Origin"
    return resp

@router.options("/upload_image")
async def options_upload_image():
    resp = Response(status_code=204)
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, x-admin-token"
    resp.headers["Vary"] = "Origin"
    return resp

# === UPLOAD VIDEO (séparé de l’upload d’image) ============================
@router.post("/upload_video")
async def upload_video(
    kind: str = Form(...),
    lat: float = Form(...),
    lng: float = Form(...),
    user_id: Optional[UUID] = Form(None),
    idempotency_key: Optional[str] = Form(None),
    file: UploadFile = File(...),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Upload vidéo robuste :
    - Vérifie droit auteur (sauf admin)
    - Normalise la vidéo pour compatibilité mobile (faststart + H.264/AAC si besoin)
    - Envoie vers Supabase (fallback disque)
    - Enregistre dans attachments
    """
    import os, uuid, time as _time, tempfile, shutil, subprocess, json
    from sqlalchemy import text
    from app.config import BASE_PUBLIC_URL, STATIC_DIR, STATIC_URL_PATH

    # -------- Admin ? --------
    is_admin = False
    try:
        admin_hdr = (request.headers.get("x-admin-token") or "").strip()
        admin_env = (
            os.getenv("ADMIN_TOKEN")
            or os.getenv("NEXT_PUBLIC_ADMIN_TOKEN")
            or ""
        ).strip()
        is_admin = bool(admin_hdr and admin_env and admin_hdr == admin_env)
    except Exception:
        pass

    # -------- Kind --------
    K = (kind or "").strip().lower()
    if K not in {"traffic","accident","fire","flood","power","water","assault","weapon","medical"}:
        raise HTTPException(status_code=400, detail="invalid kind")

    # -------- Lecture bytes --------
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty file")
    if len(data) > 40 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="video too large")

    # -------- Idempotency --------
    idem = (idempotency_key or "").strip() or None
    if idem:
        rs = await db.execute(text("SELECT id, url FROM attachments WHERE idempotency_key = :k LIMIT 1"), {"k": idem})
        row = rs.first()
        if row:
            return {"ok": True, "id": str(row.id), "url": row.url, "idempotency_key": idem}

    # -------- Droit auteur (si pas admin) --------
    if not is_admin:
        if not user_id:
            raise HTTPException(status_code=403, detail="not_owner")
        chk = text("""
            WITH me AS (SELECT ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography AS g)
            SELECT 1 FROM reports
             WHERE user_id = :uid
               AND LOWER(TRIM(kind::text))   = :k
               AND LOWER(TRIM(signal::text)) = 'cut'
               AND created_at > NOW() - INTERVAL '48 hours'
               AND ST_DWithin((geom::geography),(SELECT g FROM me),150)
             LIMIT 1
        """)
        r = await db.execute(chk, {"uid": str(user_id), "k": K, "lat": float(lat), "lng": float(lng)})
        if r.first() is None:
            raise HTTPException(status_code=403, detail="not_owner")

    # -------- Préparation fichiers temp --------
    tmpdir = tempfile.mkdtemp(prefix="ayii_vid_")
    try:
        # nom/paths
        orig_name = file.filename or f"capture_{uuid.uuid4().hex}"
        in_path  = os.path.join(tmpdir, orig_name)
        out_path = os.path.join(tmpdir, "out.mp4")  # cible finale mp4
        # écrire le fichier source
        with open(in_path, "wb") as ftmp:
            ftmp.write(data)

        # -------- ffprobe (pour savoir si déjà H.264/AAC) --------
        def _probe_codecs(path: str) -> dict:
            ffprobe = os.getenv("FFPROBE_PATH", "ffprobe")
            try:
                p = subprocess.run(
                    [ffprobe, "-v", "error", "-print_format", "json", "-show_streams", path],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True
                )
                return json.loads(p.stdout.decode("utf-8", "ignore"))
            except Exception:
                return {}

        info = _probe_codecs(in_path)
        v_codec = a_codec = None
        for st in info.get("streams", []):
            if st.get("codec_type") == "video" and not v_codec:
                v_codec = st.get("codec_name")
            if st.get("codec_type") == "audio" and not a_codec:
                a_codec = st.get("codec_name")

        # -------- Tentative 1 : remux rapide + faststart --------
        ffmpeg = os.getenv("FFMPEG_PATH", "ffmpeg")
        def _run_ffmpeg(args: list) -> bool:
            try:
                p = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
                return os.path.exists(out_path) and os.path.getsize(out_path) > 0
            except Exception:
                return False

        # Si déjà h264/aac, on remux + faststart ; sinon on ira en transcode
        did_ok = False
        if (v_codec == "h264") and (a_codec in {"aac", "mp3", "opus", "vorbis"}):
            did_ok = _run_ffmpeg([
                ffmpeg, "-y", "-i", in_path,
                "-c", "copy",
                "-movflags", "+faststart",
                out_path
            ])

        # -------- Tentative 2 : transcode propre H.264/AAC baseline --------
        if not did_ok:
            # 720p max, 24 fps, baseline, yuv420p, AAC 96k, faststart
            did_ok = _run_ffmpeg([
                ffmpeg, "-y", "-i", in_path,
                "-vf", "scale='min(720,iw)':'-2'",
                "-r", "24",
                "-c:v", "libx264",
                "-profile:v", "baseline",
                "-level", "3.0",
                "-pix_fmt", "yuv420p",
                "-preset", "veryfast",
                "-crf", "23",
                "-c:a", "aac",
                "-b:a", "96k",
                "-ac", "2",
                "-ar", "44100",
                "-movflags", "+faststart",
                out_path
            ])

        if not did_ok:
            # en dernier recours, on renvoie l’original tel quel en mp4 (peut échouer mobile)
            shutil.copy(in_path, out_path)

        # -------- Upload (Supabase d'abord, disque sinon) --------
        # Chemin lisible/partitionné pour éviter des dossiers trop gros
        bucket   = os.getenv("SUPABASE_BUCKET", "attachments")
        supa_url = (os.getenv("SUPABASE_URL") or "").rstrip("/")
        supa_key = os.getenv("SUPABASE_SERVICE_ROLE") or os.getenv("SUPABASE_SERVICE_KEY")
        yyyy = _time.strftime("%Y"); mm = _time.strftime("%m"); dd = _time.strftime("%d")
        path = f"{K}/{yyyy}/{mm}/{dd}/{int(_time.time())}-{uuid.uuid4().hex}.mp4"

        public_url: Optional[str] = None

        try:
            if supa_url and supa_key:
                import httpx
                upload_url = f"{supa_url}/storage/v1/object/{bucket}/{path}"
                headers = {
                    "Authorization": f"Bearer {supa_key}",
                    "Content-Type": "video/mp4",
                    "x-upsert": "false",
                }
                with open(out_path, "rb") as fp:
                    data_bin = fp.read()
                async with httpx.AsyncClient(timeout=120) as client:
                    r = await client.post(upload_url, headers=headers, content=data_bin)
                if r.status_code not in (200, 201):
                    raise RuntimeError(f"supabase upload failed [{r.status_code}]: {r.text}")
                public_url = f"{supa_url}/storage/v1/object/public/{bucket}/{path}"
            else:
                # fallback disque
                os.makedirs(STATIC_DIR, exist_ok=True)
                disk_path = os.path.join(STATIC_DIR, os.path.basename(path))
                shutil.copy(out_path, disk_path)
                base = (BASE_PUBLIC_URL or "").rstrip("/")
                public_url = f"{base}{STATIC_URL_PATH}/{os.path.basename(path)}" if base else f"{STATIC_URL_PATH}/{os.path.basename(path)}"
        except Exception:
            # fallback disque si l’upload supabase a raté
            os.makedirs(STATIC_DIR, exist_ok=True)
            disk_path = os.path.join(STATIC_DIR, os.path.basename(path))
            shutil.copy(out_path, disk_path)
            base = (BASE_PUBLIC_URL or "").rstrip("/")
            public_url = f"{base}{STATIC_URL_PATH}/{os.path.basename(path)}" if base else f"{STATIC_URL_PATH}/{os.path.basename(path)}"

        if not public_url:
            raise HTTPException(status_code=500, detail="no_public_url")

        # -------- DB insert --------
        ins = text("""
          INSERT INTO attachments (
            kind, geom, user_id, url, idempotency_key, created_at, is_sensitive, uploader_id
          ) VALUES (
            :k, ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography,
            :uid, :url, :idem, NOW(), TRUE, :uploader
          )
          RETURNING id
        """)
        rs = await db.execute(ins, {
            "k": K,
            "lng": float(lng),
            "lat": float(lat),
            "uid": str(user_id) if user_id else None,
            "url": public_url,
            "idem": idem,
            "uploader": str(user_id) if user_id else None,
        })
        row = rs.first()
        await db.commit()

        return {"ok": True, "id": str(row.id), "url": public_url, "idempotency_key": idem}
    finally:
        try:
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass




# --------- Upload vers Supabase Storage ----------
async def _upload_to_supabase(file_bytes: bytes, filename: str, content_type: str) -> str:
    SUPA_URL = (os.getenv("SUPABASE_URL") or "").rstrip("/")
    SUPA_KEY = os.getenv("SUPABASE_SERVICE_ROLE", "")
    BUCKET   = os.getenv("SUPABASE_BUCKET", "attachments")

    if not (SUPA_URL and SUPA_KEY and BUCKET):
        raise HTTPException(status_code=500, detail="supabase creds missing (SUPABASE_URL / SUPABASE_SERVICE_ROLE / SUPABASE_BUCKET)")

    import httpx, time as _time, uuid as _uuid
    path = f"{int(_time.time())}/{_uuid.uuid4()}-{(filename or 'photo.jpg')}"
    upload_url = f"{SUPA_URL}/storage/v1/object/{BUCKET}/{path}"
    headers = {
        "Authorization": f"Bearer {SUPA_KEY}",
        "Content-Type": content_type or "application/octet-stream",
        "x-upsert": "true",
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(upload_url, headers=headers, content=file_bytes)
    except httpx.ConnectError as e:
        raise HTTPException(502, detail=f"supabase connect error: {e}")
    except httpx.ReadTimeout as e:
        raise HTTPException(504, detail=f"supabase timeout: {e}")
    except Exception as e:
        raise HTTPException(500, detail=f"supabase http error: {e}")

    if r.status_code not in (200, 201):
        raise HTTPException(status_code=500, detail=f"supabase upload failed [{r.status_code}]: {r.text}")

    return f"{SUPA_URL}/storage/v1/object/public/{BUCKET}/{path}"

# ---------- LECTURES (outages/incidents) ----------
async def fetch_outages(db: AsyncSession, lat: float, lng: float, r_m: float):
    q_full = text(f"""
        WITH me AS (
          SELECT ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography AS g
        )
        SELECT o.id,
               o.kind::text AS kind,
               CASE WHEN o.restored_at IS NULL THEN 'active' ELSE 'restored' END AS status,
               ST_Y((o.center::geometry)) AS lat,
               ST_X((o.center::geometry)) AS lng,
               o.started_at,
               o.restored_at,
               COALESCE(att.cnt, 0)::int AS attachments_count,
               COALESCE(rep.cnt, 0)::int AS reports_count
        FROM outages o
        LEFT JOIN LATERAL (
          SELECT COUNT(*)::int AS cnt
            FROM attachments a
           WHERE a.kind::text = o.kind::text
             AND a.created_at > NOW() - INTERVAL '48 hours'
             AND ST_DWithin((a.geom::geography), (o.center::geography), 120)
        ) att ON TRUE
        LEFT JOIN LATERAL (
          SELECT COUNT(*)::int AS cnt
            FROM reports r
           WHERE LOWER(TRIM(r.signal::text))='cut'
             AND r.created_at > NOW() - INTERVAL '{POINTS_WINDOW_MIN} minutes'
             AND r.kind::text = o.kind::text
             AND ST_DWithin((r.geom::geography), (o.center::geography), 120)
        ) rep ON TRUE
        WHERE ST_DWithin((o.center::geography), (SELECT g FROM me), :r)
        ORDER BY o.started_at DESC NULLS LAST, o.id DESC
    """)
    q_min = text(f"""
        WITH me AS (
          SELECT ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography AS g
        )
        SELECT o.id,
               o.kind::text AS kind,
               CASE WHEN o.restored_at IS NULL THEN 'active' ELSE 'restored' END AS status,
               ST_Y((o.center::geometry)) AS lat,
               ST_X((o.center::geometry)) AS lng,
               o.started_at,
               o.restored_at,
               0::int AS attachments_count,
               0::int AS reports_count
        FROM outages o
        WHERE ST_DWithin((o.center::geography), (SELECT g FROM me), :r)
        ORDER BY o.started_at DESC NULLS LAST, o.id DESC
    """)
    try:
        res = await db.execute(q_full, {"lng": lng, "lat": lat, "r": r_m})
    except Exception:
        await db.rollback()
        res = await db.execute(q_min, {"lng": lng, "lat": lat, "r": r_m})
    rows = res.fetchall()
    return [
        {
            "id": r.id, "kind": r.kind, "status": r.status,
            "lat": float(r.lat), "lng": float(r.lng),
            "started_at": getattr(r, "started_at", None),
            "restored_at": getattr(r, "restored_at", None),
            "attachments_count": getattr(r, "attachments_count", 0),
            "reports_count": getattr(r, "reports_count", 0),
        } for r in rows
    ]

async def fetch_incidents(db: AsyncSession, lat: float, lng: float, r_m: float):
    q_full = text(f"""
        WITH me AS (
          SELECT ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography AS g
        )
        SELECT i.id,
               i.kind::text AS kind,
               CASE WHEN i.restored_at IS NULL THEN 'active' ELSE 'restored' END AS status,
               ST_Y((i.center::geometry)) AS lat,
               ST_X((i.center::geometry)) AS lng,
               i.started_at,
               i.restored_at,
               COALESCE(att.cnt, 0)::int AS attachments_count,
               COALESCE(rep.cnt, 0)::int AS reports_count
        FROM incidents i
        LEFT JOIN LATERAL (
          SELECT COUNT(*)::int AS cnt
            FROM attachments a
           WHERE a.kind::text = i.kind::text
             AND a.created_at > NOW() - INTERVAL '48 hours'
             AND ST_DWithin((a.geom::geography), (i.center::geography), 120)
        ) att ON TRUE
        LEFT JOIN LATERAL (
          SELECT COUNT(*)::int AS cnt
            FROM reports r
           WHERE LOWER(TRIM(r.signal::text))='cut'
             AND r.created_at > NOW() - INTERVAL '{POINTS_WINDOW_MIN} minutes'
             AND r.kind::text = i.kind::text
             AND ST_DWithin((r.geom::geography), (i.center::geography), 120)
        ) rep ON TRUE
        WHERE ST_DWithin((i.center::geography), (SELECT g FROM me), :r)
        ORDER BY i.started_at DESC NULLS LAST, i.id DESC
    """)
    q_min = text("""
        WITH me AS (
          SELECT ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography AS g
        )
        SELECT i.id,
               i.kind::text AS kind,
               CASE WHEN i.restored_at IS NULL THEN 'active' ELSE 'restored' END AS status,
               ST_Y((i.center::geometry)) AS lat,
               ST_X((i.center::geometry)) AS lng,
               i.started_at,
               i.restored_at,
               0::int AS attachments_count,
               0::int AS reports_count
        FROM incidents i
        WHERE ST_DWithin((i.center::geography), (SELECT g FROM me), :r)
        ORDER BY i.started_at DESC NULLS LAST, i.id DESC
    """)
    try:
        res = await db.execute(q_full, {"lng": lng, "lat": lat, "r": r_m})
    except Exception:
        await db.rollback()
        res = await db.execute(q_min, {"lng": lng, "lat": lat, "r": r_m})
    rows = res.fetchall()
    return [
        {
            "id": r.id, "kind": r.kind, "status": r.status,
            "lat": float(r.lat), "lng": float(r.lng),
            "started_at": getattr(r, "started_at", None),
            "restored_at": getattr(r, "restored_at", None),
            "attachments_count": getattr(r, "attachments_count", 0),
            "reports_count": getattr(r, "reports_count", 0),
        } for r in rows
    ]

# ---------- LECTURES GLOBAL (show_all) ----------
async def fetch_outages_all(db: AsyncSession, limit: int = 2000):
    q = text(f"""
        SELECT o.id,
               o.kind::text AS kind,
               CASE WHEN o.restored_at IS NULL THEN 'active' ELSE 'restored' END AS status,
               ST_Y((o.center::geometry)) AS lat,
               ST_X((o.center::geometry)) AS lng,
               o.started_at,
               o.restored_at,
               COALESCE(att.cnt, 0)::int AS attachments_count,
               COALESCE(rep.cnt, 0)::int AS reports_count
        FROM outages o
        LEFT JOIN LATERAL (
          SELECT COUNT(*)::int AS cnt
            FROM attachments a
           WHERE a.kind::text = o.kind::text
             AND a.created_at > NOW() - INTERVAL '48 hours'
             AND ST_DWithin((a.geom::geography), (o.center::geography), 120)
        ) att ON TRUE
        LEFT JOIN LATERAL (
          SELECT COUNT(*)::int AS cnt
            FROM reports r
           WHERE LOWER(TRIM(r.signal::text))='cut'
             AND r.created_at > NOW() - INTERVAL '{POINTS_WINDOW_MIN} minutes'
             AND r.kind::text = o.kind::text
             AND ST_DWithin((r.geom::geography), (o.center::geography), 120)
        ) rep ON TRUE
        WHERE o.restored_at IS NULL
        ORDER BY o.started_at DESC NULLS LAST, o.id DESC
        LIMIT :lim
    """)
    res = await db.execute(q, {"lim": limit})
    rows = res.fetchall()
    return [
        {
            "id": r.id, "kind": r.kind, "status": r.status,
            "lat": float(r.lat), "lng": float(r.lng),
            "started_at": getattr(r, "started_at", None),
            "restored_at": getattr(r, "restored_at", None),
            "attachments_count": getattr(r, "attachments_count", 0),
            "reports_count": getattr(r, "reports_count", 0),
        } for r in rows
    ]

async def fetch_incidents_all(db: AsyncSession, limit: int = 2000):
    q = text(f"""
        SELECT i.id,
               i.kind::text AS kind,
               CASE WHEN i.restored_at IS NULL THEN 'active' ELSE 'restored' END AS status,
               ST_Y((i.center::geometry)) AS lat,
               ST_X((i.center::geometry)) AS lng,
               i.started_at,
               i.restored_at,
               COALESCE(att.cnt, 0)::int AS attachments_count,
               COALESCE(rep.cnt, 0)::int AS reports_count
        FROM incidents i
        LEFT JOIN LATERAL (
          SELECT COUNT(*)::int AS cnt
            FROM attachments a
           WHERE a.kind::text = i.kind::text
             AND a.created_at > NOW() - INTERVAL '48 hours'
             AND ST_DWithin((a.geom::geography), (i.center::geography), 120)
        ) att ON TRUE
        LEFT JOIN LATERAL (
          SELECT COUNT(*)::int AS cnt
            FROM reports r
           WHERE LOWER(TRIM(r.signal::text))='cut'
             AND r.created_at > NOW() - INTERVAL '{POINTS_WINDOW_MIN} minutes'
             AND r.kind::text = i.kind::text
             AND ST_DWithin((r.geom::geography), (i.center::geography), 120)
        ) rep ON TRUE
        WHERE i.restored_at IS NULL
        ORDER BY i.started_at DESC NULLS LAST, i.id DESC
        LIMIT :lim
    """)
    res = await db.execute(q, {"lim": limit})
    rows = res.fetchall()
    return [
        {
            "id": r.id, "kind": r.kind, "status": r.status,
            "lat": float(r.lat), "lng": float(r.lng),
            "started_at": getattr(r, "started_at", None),
            "restored_at": getattr(r, "restored_at", None),
            "attachments_count": getattr(r, "attachments_count", 0),
            "reports_count": getattr(r, "reports_count", 0),
        } for r in rows
    ]

# --- Helper pour /map : zones d’alerte via cluster DBSCAN ---

# --- Helper pour /map : zones d’alerte via cluster DBSCAN ---
async def fetch_alert_zones(db: AsyncSession, lat: float, lng: float, r_m: float):
    """
    Regroupe les reports 'cut' récents par proximité (DBSCAN-like)
    et renvoie des clusters {kind, count, lat, lng} prêts pour la carte.
    Compatible avec tous les types (incidents + outages).
    """
    window_min = int(ALERT_WINDOW_H) * 60  # passer heures -> minutes
    group_radius_m = float(ALERT_RADIUS_M)
    threshold = int(ALERT_THRESHOLD)

    sql = text(f"""
        WITH me AS (
          SELECT ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography AS g
        ),
        pts AS (
          SELECT
            id,
            kind::text AS kind,
            ST_SnapToGrid(ST_Transform((geom::geometry),3857), 1.0) AS g3857,
            (geom::geometry) AS g4326
          FROM reports
          WHERE created_at > NOW() - INTERVAL '{window_min} minutes'
            AND LOWER(TRIM(signal::text))='cut'
            AND ST_DWithin((geom::geography), (SELECT g FROM me), :r)
            AND kind IN ('traffic','accident','fire','flood','power','water','assault','weapon','medical')
        ),
        clus AS (
          SELECT
            kind,
            ST_ClusterDBSCAN(g3857, eps := :eps, minpoints := 2) OVER () AS cid,
            g4326
          FROM pts
        ),
        agg AS (
          SELECT
            kind,
            cid,
            COUNT(*)::int AS n,
            ST_Transform(ST_Centroid(ST_Collect(g4326)), 4326) AS center4326
          FROM clus
          WHERE cid IS NOT NULL
          GROUP BY kind, cid
        ),
        zones AS (
          SELECT
            a.kind,
            a.n,
            ST_Y(a.center4326) AS lat,
            ST_X(a.center4326) AS lng
          FROM agg a
          WHERE a.n >= :threshold
        )
        SELECT z.kind, z.n, z.lat, z.lng
        FROM zones z
        WHERE NOT EXISTS (
          SELECT 1
          FROM acks ak
          WHERE ak.kind = z.kind
            AND ST_DWithin(
              (ST_SetSRID(ST_MakePoint(z.lng, z.lat),4326)::geography),
              ak.geom,
              :ack_r
            )
        )
        ORDER BY z.kind, z.n DESC
    """)

    params = {
        "lat": float(lat),
        "lng": float(lng),
        "r": float(r_m),
        "eps": group_radius_m,
        "threshold": threshold,
        "ack_r": group_radius_m,
    }

    try:
        res = await db.execute(sql, params)
        rows = res.fetchall()
    except Exception as e:
        await db.rollback()
        print(f"⚠️ fetch_alert_zones SQL error: {e}")
        return []

    return [
        {"kind": r.kind, "count": int(r.n), "lat": float(r.lat), "lng": float(r.lng)}
        for r in rows
    ]





# ---------- ENDPOINT /map ----------
@router.get("/map")
async def map_endpoint(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    radius_km: float = Query(5.0, gt=0, le=50),
    show_all: bool = Query(False, description="Si true: renvoie tous les événements actifs (cap)."),
    response: Response = None,
    db: AsyncSession = Depends(get_db),
):
    def nowz():
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    try:
        # 0) Auto-clôture incidents/outages anciens (si activé)
        try:
            if os.getenv("AUTO_EXPIRE_ENABLED", "1") != "0":
                await db.execute(text(f"""
                    UPDATE incidents
                       SET restored_at = COALESCE(restored_at, NOW())
                     WHERE restored_at IS NULL
                       AND started_at  < NOW() - INTERVAL '{AUTO_EXPIRE_H} hours'
                """))
                await db.execute(text(f"""
                    UPDATE outages
                       SET restored_at = COALESCE(restored_at, NOW())
                     WHERE restored_at IS NULL
                       AND started_at  < NOW() - INTERVAL '{AUTO_EXPIRE_H} hours'
                """))
                await db.commit()
        except Exception:
            await db.rollback()

        # 👉 Mode GLOBAL: on peut alléger (pas de last_reports ni alert_zones)
        if show_all:
            outages   = await fetch_outages_all(db, limit=2000)
            incidents = await fetch_incidents_all(db, limit=2000)
            payload = {
                "outages": outages,
                "incidents": incidents,
                "alert_zones": [],     # allégé en global
                "last_reports": [],
                "server_now": nowz(),
            }
            if response is not None:
                response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
                response.headers["Pragma"] = "no-cache"
            return payload

        # --- mode LOCAL (comportement historique) ---
        r_m = float(radius_km * 1000.0)

        outages   = await fetch_outages(db, lat, lng, r_m)
        incidents = await fetch_incidents(db, lat, lng, r_m)
        alert_zones = await fetch_alert_zones(db, lat, lng, r_m)

        # derniers reports pour les badges / info
        q_rep = text(f"""
            WITH me AS (
              SELECT ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography AS g
            )
            SELECT id,
                   kind::text   AS kind,
                   signal::text AS signal,
                   ST_Y((geom::geometry)) AS lat,
                   ST_X((geom::geometry)) AS lng,
                   user_id,
                   created_at
              FROM reports
             WHERE ST_DWithin((geom::geography), (SELECT g FROM me), :r)
               AND LOWER(TRIM(signal::text)) = 'cut'
               AND created_at > NOW() - INTERVAL '{POINTS_WINDOW_MIN} minutes'
             ORDER BY created_at DESC
             LIMIT :max
        """)
        res_rep = await db.execute(q_rep, {"lng": lng, "lat": lat, "r": r_m, "max": MAX_REPORTS})
        last_reports = [
            {
                "id": r.id,
                "kind": r.kind,
                "signal": r.signal,
                "lat": float(r.lat),
                "lng": float(r.lng),
                "user_id": r.user_id,
                "created_at": r.created_at,
            }
            for r in res_rep.fetchall()
        ]

        payload = {
            "outages": outages,
            "incidents": incidents,
            "alert_zones": alert_zones,   # 👈 nouveau
            "last_reports": last_reports,
            "server_now": nowz(),
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
        return {
            "outages": [],
            "incidents": [],
            "alert_zones": [],
            "last_reports": [],
            "server_now": nowz(),
            "error": f"{type(e).__name__}: {e}",
        }


# --------- POST /report ----------
class ReportIn(BaseModel):
    kind: str            # "power" | "water" | "traffic" | "accident" | "fire" | "flood"
    signal: str          # "cut" | "restored"
    lat: float
    lng: float
    user_id: Optional[str] = None
    idempotency_key: Optional[str] = None


@router.post("/report")
async def post_report(
    p: ReportIn = Body(...),
    db: AsyncSession = Depends(get_db),
    x_admin_token: Optional[str] = Header(default=None),
):
    # Timeout SQL "local" pour éviter que la requête reste bloquée côté DB
    try:
        await db.execute(text("SET LOCAL statement_timeout = '8s'"))
    except Exception:
        await db.rollback()

    kind = (p.kind or "").lower().strip()
    signal = (p.signal or "").lower().strip()
    if kind not in ALLOWED_KINDS:
        raise HTTPException(400, "invalid kind")

    if signal not in {"cut","restored"}:
        raise HTTPException(400, "invalid signal")

    uid = _to_uuid_or_none(p.user_id)
    is_admin = (x_admin_token or "").strip() == ADMIN_TOKEN
    idem = (p.idempotency_key or "").strip() or None

    # Upsert user (si user_id fourni) pour éviter FK brisée
    if uid:
        try:
            await db.execute(
                text("INSERT INTO app_users(id) VALUES(CAST(:uid AS uuid)) ON CONFLICT (id) DO NOTHING"),
                {"uid": uid}
            )
            await db.commit()
        except Exception:
            await db.rollback()

    # 1) Enregistrer le report (idempotent)
    inserted_id = None
    try:
        res = await db.execute(text("""
            INSERT INTO reports(kind, signal, geom, user_id, created_at, idempotency_key)
            SELECT
              CAST(:kind   AS report_kind),
              CAST(:signal AS report_signal),
              ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography,
              CAST(NULLIF(:uid,'') AS uuid),
              NOW(),
              NULLIF(:idem,'')::text
            WHERE
              (:idem IS NULL OR :idem = '')
              OR NOT EXISTS (SELECT 1 FROM reports WHERE idempotency_key = NULLIF(:idem,'')::text)
            RETURNING id
        """), {"kind": kind, "signal": signal, "lng": p.lng, "lat": p.lat, "uid": (uid or ""), "idem": idem})
        row = res.fetchone()
        await db.commit()
        inserted_id = row[0] if row else None
    except Exception:
        await db.rollback()
        try:
            res = await db.execute(text("""
                INSERT INTO reports(kind, signal, geom, user_id, created_at, idempotency_key)
                SELECT
                  CAST(:kind   AS text),
                  CAST(:signal AS text),
                  ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography,
                  CAST(NULLIF(:uid,'') AS uuid),
                  NOW(),
                  NULLIF(:idem,'')::text
                WHERE
                  (:idem IS NULL OR :idem = '')
                  OR NOT EXISTS (SELECT 1 FROM reports WHERE idempotency_key = NULLIF(:idem,'')::text)
                RETURNING id
            """), {"kind": kind, "signal": signal, "lng": p.lng, "lat": p.lat, "uid": (uid or ""), "idem": idem})
            row = res.fetchone()
            await db.commit()
            inserted_id = row[0] if row else None
        except Exception as e2:
            await db.rollback()
            raise HTTPException(500, f"report insert failed: {e2}")
            
        
    

    # 2) Mise à jour incidents/outages (vérité carte)
    try:
        try:
            await db.execute(text("SET LOCAL statement_timeout = '6s'"))
        except Exception:
            await db.rollback()

        if signal == "cut":
            if kind in ("power","water"):
                # OUTAGES
                try:
                    await db.execute(text("""
                        WITH me AS (SELECT ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography AS g)
                        INSERT INTO outages(kind, center, started_at, restored_at)
                        SELECT CAST(:kind AS outage_kind), (SELECT g FROM me), NOW(), NULL
                        WHERE NOT EXISTS (
                          SELECT 1 FROM outages i
                           WHERE i.kind = CAST(:kind AS outage_kind)
                             AND i.restored_at IS NULL
                             AND ST_DWithin(i.center, (SELECT g FROM me), 120)
                        )
                    """), {"kind": kind, "lng": p.lng, "lat": p.lat})
                except Exception:
                    await db.execute(text("""
                        WITH me AS (SELECT ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography AS g)
                        INSERT INTO outages(kind, center, started_at, restored_at)
                        SELECT CAST(:kind AS text), (SELECT g FROM me), NOW(), NULL
                        WHERE NOT EXISTS (
                          SELECT 1 FROM outages i
                           WHERE i.kind = CAST(:kind AS text)
                             AND i.restored_at IS NULL
                             AND ST_DWithin(i.center, (SELECT g FROM me), 120)
                        )
                    """), {"kind": kind, "lng": p.lng, "lat": p.lat})
                await db.commit()
            else:
                # INCIDENTS
                await db.execute(text("""
                    WITH me AS (SELECT ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography AS g)
                    INSERT INTO incidents(kind, center, started_at, restored_at)
                    SELECT CAST(:kind AS text), (SELECT g FROM me), NOW(), NULL
                    WHERE NOT EXISTS (
                      SELECT 1 FROM incidents i
                       WHERE i.kind = CAST(:kind AS text)
                         AND i.restored_at IS NULL
                         AND ST_DWithin(i.center, (SELECT g FROM me), 120)
                    )
                """), {"kind": kind, "lng": p.lng, "lat": p.lat})
                await db.commit()
        else:
            # RESTORED — ownership si non-admin
            if not is_admin:
                if uid:
                    q = await db.execute(text("""
                        WITH me AS (SELECT ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography AS g)
                        SELECT 1
                          FROM reports r
                         WHERE r.kind=:kind AND lower(trim(r.signal::text))='cut'
                           AND r.user_id = CAST(:uid AS uuid)
                           AND r.created_at >= NOW() - INTERVAL '24 hours'
                           AND ST_DWithin(r.geom, (SELECT g FROM me), :ownr)
                         LIMIT 1
                    """), {"kind": kind, "uid": uid, "lng": p.lng, "lat": p.lat, "ownr": OWNERSHIP_RADIUS_M})
                    if q.first() is None:
                        raise HTTPException(403, "not_owner")
                else:
                    raise HTTPException(403, "not_owner")

            if kind in ("power","water"):
                try:
                    await db.execute(text("""
                        WITH me AS (SELECT ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography AS g)
                        UPDATE outages i
                           SET restored_at = COALESCE(i.restored_at, NOW())
                         WHERE i.kind = CAST(:kind AS outage_kind)
                           AND i.restored_at IS NULL
                           AND ST_DWithin(i.center, (SELECT g FROM me), 150)
                    """), {"kind": kind, "lng": p.lng, "lat": p.lat})
                except Exception:
                    await db.execute(text("""
                        WITH me AS (SELECT ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography AS g)
                        UPDATE outages i
                           SET restored_at = COALESCE(i.restored_at, NOW())
                         WHERE i.kind = CAST(:kind AS text)
                           AND i.restored_at IS NULL
                           AND ST_DWithin(i.center, (SELECT g FROM me), 150)
                    """), {"kind": kind, "lng": p.lng, "lat": p.lat})
                await db.commit()
            else:
                await db.execute(text("""
                    WITH me AS (SELECT ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography AS g)
                    UPDATE incidents i
                       SET restored_at = COALESCE(i.restored_at, NOW())
                     WHERE i.kind = CAST(:kind AS text)
                       AND i.restored_at IS NULL
                       AND ST_DWithin(i.center, (SELECT g FROM me), 150)
                """), {"kind": kind, "lng": p.lng, "lat": p.lat})
                await db.commit()

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(500, f"events update failed: {e}")

    return {"ok": True, "id": inserted_id, "idempotency_key": idem}

# --------- Admin: factory reset ----------
@router.post("/admin/factory_reset")
async def admin_factory_reset(request: Request, db: AsyncSession = Depends(get_db)):
    _check_admin_token(request)
    try:
        for ddl in [
            "TRUNCATE TABLE reports RESTART IDENTITY CASCADE",
            "TRUNCATE TABLE incidents RESTART IDENTITY CASCADE",
            "TRUNCATE TABLE outages RESTART IDENTITY CASCADE",
            "TRUNCATE TABLE attachments RESTART IDENTITY CASCADE"
        ]:
            try:
                await db.execute(text(ddl))
            except Exception:
                await db.rollback()

        await db.commit()

        try:
            await db.execute(text("ALTER TABLE incidents ADD COLUMN IF NOT EXISTS restored_at timestamp NULL"))
            await db.execute(text("ALTER TABLE outages   ADD COLUMN IF NOT EXISTS restored_at timestamp NULL"))
            await db.execute(text("CREATE INDEX IF NOT EXISTS idx_incidents_center ON incidents USING GIST ((center::geometry))"))
            await db.execute(text("CREATE INDEX IF NOT EXISTS idx_outages_center   ON outages   USING GIST ((center::geometry))"))
            await db.execute(text("CREATE INDEX IF NOT EXISTS idx_incidents_kind ON incidents(kind)"))
            await db.execute(text("CREATE INDEX IF NOT EXISTS idx_outages_kind   ON outages(kind)"))
            await db.commit()
        except Exception:
            await db.rollback()

        return {"ok": True}
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"factory_reset failed: {e}")

# --------- Upload image ----------
@router.post("/upload_image")
async def upload_image(
    kind: str = Form(...),
    lat: float = Form(...),
    lng: float = Form(...),
    user_id: Optional[UUID] = Form(None),
    idempotency_key: Optional[str] = Form(None),
    file: UploadFile = File(...),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
):
    # --- Admin simple (header x-admin-token)
    is_admin = False
    try:
        admin_hdr = (request.headers.get("x-admin-token") or "").strip()
        if admin_hdr and admin_hdr == (os.getenv("ADMIN_TOKEN") or os.getenv("NEXT_PUBLIC_ADMIN_TOKEN") or ""):
            is_admin = True
    except Exception:
        pass

    K = (kind or "").strip().lower()
    if K not in ALLOWED_KINDS:
         raise HTTPException(status_code=400, detail="invalid kind")


    # --- lecture du fichier
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty file")

    ctype = (file.content_type or "").lower().strip()
    is_image = ctype.startswith("image/")
    is_video = ctype.startswith("video/")

    if not (is_image or is_video):
        # accepte uniquement image/* ou video/* (webm/mp4)
        raise HTTPException(status_code=415, detail=f"unsupported content-type: {ctype or 'unknown'}")

    # bornes de taille : image 15Mo, vidéo 50Mo
    if is_image and len(data) > 15 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="image too large")
    if is_video and len(data) > 50 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="video too large")

    # --- idempotency
    idem = (idempotency_key or "").strip() or None
    if idem:
        q = text("SELECT id, url FROM attachments WHERE idempotency_key = :k LIMIT 1")
        rs = await db.execute(q, {"k": idem})
        row = rs.first()
        if row:
            return {
                "ok": True,
                "id": str(row.id),
                "url": row.url if is_admin else None,  # ne montre l'URL qu'à l’admin
                "idempotency_key": idem,
            }

    # --- Ownership check : si pas admin, l'uploader doit avoir un report récent proche
    if not is_admin:
        if not user_id:
            raise HTTPException(status_code=403, detail="not_owner")
        chk = text("""
            WITH me AS (SELECT ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography AS g)
            SELECT 1
              FROM reports
             WHERE user_id = :uid
               AND LOWER(TRIM(kind::text))   = :k
               AND LOWER(TRIM(signal::text)) = 'cut'
               AND created_at > NOW() - INTERVAL '48 hours'
               AND ST_DWithin((geom::geography),(SELECT g FROM me),150)
             LIMIT 1
        """)
        rs = await db.execute(chk, {"uid": str(user_id), "k": K, "lat": lat, "lng": lng})
        if rs.first() is None:
            raise HTTPException(status_code=403, detail="not_owner")

    # --- choix extension/filename
    ext = ".jpg"
    if is_video:
        if "mp4" in ctype:
            ext = ".mp4"
        elif "webm" in ctype:
            ext = ".webm"
        else:
            ext = ".mp4"
    else:
        if "jpeg" in ctype:
            ext = ".jpg"
        elif "png" in ctype:
            ext = ".png"
        elif "webp" in ctype:
            ext = ".webp"
        else:
            ext = ".jpg"

    # --- stockage Supabase (si configuré) sinon local
    url_public = None
    bucket   = os.getenv("SUPABASE_BUCKET", "attachments")
    supa_url = (os.getenv("SUPABASE_URL") or "").rstrip("/")
    supa_key = os.getenv("SUPABASE_SERVICE_ROLE") or os.getenv("SUPABASE_SERVICE_KEY")

    try:
        if supa_url and supa_key:
            import httpx
            path = f"{K}/{int(time.time())}-{uuid.uuid4()}{ext}"
            upload_url = f"{supa_url}/storage/v1/object/{bucket}/{path}"
            headers = {
                "Authorization": f"Bearer {supa_key}",
                "Content-Type": ctype or ("video/mp4" if is_video else "image/jpeg"),
                "x-upsert": "false",
            }
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(upload_url, headers=headers, content=data)
            if r.status_code not in (200, 201):
                raise HTTPException(status_code=502, detail=f"supabase upload failed: {r.status_code}")
            url_public = f"{supa_url}/storage/v1/object/public/{bucket}/{path}"
        else:
            # local /static (dev)
            os.makedirs(STATIC_DIR, exist_ok=True)
            path = f"{K}-{uuid.uuid4()}{ext}"
            disk_path = os.path.join(STATIC_DIR, path)
            with open(disk_path, "wb") as fp:
                fp.write(data)
            base = (BASE_PUBLIC_URL or "").rstrip("/")
            url_public = f"{base}{STATIC_URL_PATH}/{path}" if base else f"{STATIC_URL_PATH}/{path}"
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"storage_error: {e}")

    if not url_public:
        raise HTTPException(status_code=500, detail="no_public_url")

    # --- insert DB
    ins = text("""
        INSERT INTO attachments (
            kind, geom, user_id, url, idempotency_key, created_at,
            is_sensitive, uploader_id
        )
        VALUES (
            :k,
            ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography,
            :uid,
            :url,
            :idem,
            NOW(),
            TRUE,
            :uploader
        )
        RETURNING id
    """)
    rs = await db.execute(
        ins,
        {
            "k": K,
            "lng": float(lng),
            "lat": float(lat),
            "uid": str(user_id) if user_id else None,
            "url": url_public,
            "idem": idem,
            "uploader": str(user_id) if user_id else None,
        },
    )
    new_id = rs.scalar() if hasattr(rs, "scalar") else (rs.first().id if rs.first() else None)
    await db.commit()

    return {
        "ok": True,
        "id": str(new_id) if new_id else None,
        "url": url_public if is_admin else None,  # L’URL n’est renvoyée qu’à l’admin
        "idempotency_key": idem,
    }





@router.get("/admin/supabase_status")
async def supabase_status():
    return {
        "SUPABASE_URL_set": bool(os.getenv("SUPABASE_URL")),
        "SUPABASE_SERVICE_ROLE_set": bool(os.getenv("SUPABASE_SERVICE_ROLE")),
        "SUPABASE_BUCKET": os.getenv("SUPABASE_BUCKET", "attachments"),
    }

# --------- RESET USER ----------
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

    # build CSV
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["table","id","kind","status","lat","lng","started_at","restored_at","duration_min"])
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

# --- GeoJSON exports ---
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

# --- Attachments près d'un point ---

from typing import Optional
from uuid import UUID
import os
from fastapi import HTTPException, Query, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

@router.get("/attachments_near")
async def attachments_near(
    kind: str = Query(...),
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    radius_m: int = Query(150, ge=10, le=2000),
    hours: int = Query(48, ge=1, le=168),
    viewer_user_id: Optional[UUID] = Query(
        None,
        description="Permet à l'auteur de voir sa propre image",
    ),
    debug: int = Query(0),
    request: Request = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Version 'qui marchait' :
    - admin voit tout
    - auteur d'un report proche (même kind) voit
    - les autres ne voient pas l'URL
    - ?raw=1 → redirection directe vers le 1er média autorisé
    """
    import os
    from fastapi.responses import RedirectResponse
    from sqlalchemy import text

    k = (kind or "").strip().lower()
    if k not in ALLOWED_KINDS:
        raise HTTPException(status_code=400, detail="invalid kind")

    # 1) admin ?
    is_admin = False
    try:
        admin_hdr = (request.headers.get("x-admin-token") or "").strip()
        tok = (os.getenv("ADMIN_TOKEN") or "").strip()
        is_admin = bool(tok) and admin_hdr == tok
    except Exception:
        pass

    try:
        # 2) on récupère les attachments proches
        rs = await db.execute(
            text("""
                WITH me AS (
                    SELECT ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography AS g
                )
                SELECT
                    id,
                    url,
                    ST_Y(geom::geometry) AS lat,
                    ST_X(geom::geometry) AS lng,
                    user_id,
                    created_at
                FROM attachments
                WHERE LOWER(TRIM(kind::text)) = :k
                  AND created_at > NOW() - (:hours * INTERVAL '1 hour')
                  AND ST_DWithin(geom::geography, (SELECT g FROM me), :r)
                ORDER BY created_at DESC, id DESC
                LIMIT 200
            """),
            {"k": k, "lng": lng, "lat": lat, "r": radius_m, "hours": int(hours)},
        )
        rows = rs.mappings().all()

        # 3) est-ce que le viewer est bien l'auteur d'un report proche ?
        owner_ok = False
        if (not is_admin) and viewer_user_id:
            chk = await db.execute(
                text("""
                    WITH me AS (
                        SELECT ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography AS g
                    )
                    SELECT 1
                      FROM reports
                     WHERE user_id = :uid
                       AND LOWER(TRIM(kind::text))   = :k
                       AND LOWER(TRIM(signal::text)) = 'cut'
                       AND created_at > NOW() - (:hours * INTERVAL '1 hour')
                       AND ST_DWithin(geom::geography, (SELECT g FROM me), :r)
                     LIMIT 1
                """),
                {
                    "uid": str(viewer_user_id),
                    "k": k,
                    "lng": lng,
                    "lat": lat,
                    "r": radius_m,
                    "hours": int(hours),
                },
            )
            owner_ok = (chk.first() is not None)

        out = []
        for r in rows:
            raw_url = r["url"]
            signed = None

            # on essaie de signer seulement si on a le droit de voir
            if raw_url and (is_admin or owner_ok):
                try:
                    signed = await get_signed_cached(raw_url, cache_ttl=60, link_ttl_sec=300)
                except Exception:
                    if debug:
                        signed = None

            # deviner le mime juste pour le front
            guessed_mime = None
            final_url = signed or raw_url
            if final_url:
                low = final_url.lower()
                if low.endswith(".jpg") or low.endswith(".jpeg"):
                    guessed_mime = "image/jpeg"
                elif low.endswith(".png"):
                    guessed_mime = "image/png"
                elif low.endswith(".webp"):
                    guessed_mime = "image/webp"
                elif low.endswith(".mp4"):
                    guessed_mime = "video/mp4"
                elif low.endswith(".webm"):
                    guessed_mime = "video/webm"

            if is_admin or owner_ok:
                out.append({
                    "id": str(r["id"]),
                    "kind": k,
                    "lat": float(r["lat"]),
                    "lng": float(r["lng"]),
                    "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                    "url": final_url,
                    "mime_type": guessed_mime,
                    "uploader_id": str(r["user_id"]) if r["user_id"] else None,
                })
            else:
                # pas le droit → on masque l’URL
                out.append({
                    "id": str(r["id"]),
                    "kind": k,
                    "lat": float(r["lat"]),
                    "lng": float(r["lng"]),
                    "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                    "url": None,
                    "note": "📷 Média réservé à l'auteur ou à l'admin",
                })

        # 4) si ?raw=1 → on redirige vers le 1er média accessible
        if request.query_params.get("raw") == "1":
            for item in out:
                if item.get("url"):
                    return RedirectResponse(item["url"])
            return out

        return out

    except Exception as e:
        if debug:
            raise HTTPException(status_code=500, detail=f"attachments_near error: {e}")
        raise HTTPException(status_code=500, detail="attachments_near error")



# --- Agrégations CSV (reports/events) ---
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
        # on agrège en UNION ALL puis regroupement Python
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
            if by == "day":
                key = (str(day),)
            elif by == "kind":
                key = (kindv,)
            elif by == "day_kind":
                key = (str(day), kindv)
            else:
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
                # moyenne sur éléments avec durée (approx via dur_sum / n)
                avg = round(val["dur_sum"] / val["n"], 2)
            row = list(key) + [val["n"], avg,
                               round(val["dur_min"],2) if val["dur_min"] is not None else "",
                               round(val["dur_max"],2) if val["dur_max"] is not None else ""]
            w.writerow(row)

    buf.seek(0)
    return StreamingResponse(buf, media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=aggregated.csv"})

from fastapi import status

class AckIn(BaseModel):
    kind: str
    lat: float
    lng: float
    responder: Optional[str] = "firefighter"

@router.post("/responder/ack", status_code=status.HTTP_201_CREATED)
async def responder_ack(
    p: AckIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    token: Optional[str] = Query(None)
):
    # auth très simple: header x-admin-token OU token=? (RESPONDER_TOKEN)
    ok = False
    if ADMIN_TOKEN and request.headers.get("x-admin-token","").strip() == ADMIN_TOKEN:
        ok = True
    if not ok and RESPONDER_TOKEN and (token or "").strip() == RESPONDER_TOKEN:
        ok = True
    if not ok:
        raise HTTPException(status_code=401, detail="unauthorized")

    K = (p.kind or "").strip().lower()
    if K not in {"traffic","accident","fire","flood","power","water"}:
        raise HTTPException(400, "invalid kind")

    try:
        await db.execute(
            text("""
              INSERT INTO responder_claims(kind, center, responder, created_at)
              VALUES (:k, ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography, :r, NOW())
            """),
            {"k": K, "lng": p.lng, "lat": p.lat, "r": (p.responder or "firefighter")}
        )
        await db.commit()
        return {"ok": True}
    except Exception as e:
        await db.rollback()
        raise HTTPException(500, f"ack failed: {e}")
    
# ---------- ZONES D’ALERTE (lecture) ----------
# routes_alert_zones.py
import os
from fastapi import APIRouter, Query, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from typing import Optional
from ..db import get_db  # adapte si besoin

@router.get("/alert_zones")
async def alert_zones(
    kind: str = Query(..., description="fire|traffic|accident|flood|power|water"),
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    radius_km: float = Query(1.0, ge=0.1, le=50),
    hours: int = Query(int(os.getenv("ALERT_WINDOW_HOURS", "3")), ge=1, le=72),
    min_count: int = Query(int(os.getenv("ALERT_MIN_REPORTS", "3")), ge=2, le=50),
    cell_m: int = Query(int(os.getenv("ALERT_RADIUS_M", "150")), ge=50, le=1000),
    db: AsyncSession = Depends(get_db),
):
    k = (kind or "").strip().lower()
    if k not in ALLOWED_KINDS:
        raise HTTPException(status_code=400, detail="invalid kind")


    # ~150 m → degrés
    cell_deg = max(0.0003, min(0.01, cell_m / 111_000.0))

    sql = text("""
      WITH me AS (
        SELECT ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography AS g
      ),
      base AS (
        SELECT id, kind, created_at, (geom::geography) AS gg
        FROM reports
        WHERE LOWER(TRIM(kind::text))   = :kind
          AND LOWER(TRIM(signal::text)) = 'cut'
          AND created_at > NOW() - make_interval(hours => :hours)
          AND ST_DWithin((geom::geography), (SELECT g FROM me), :rad_m)
      ),
      cells AS (
        SELECT
          kind,
          ST_SnapToGrid((gg::geometry), :cell_deg, :cell_deg) AS grid,
          gg
        FROM base
      ),
      grouped AS (
        SELECT
          kind,
          grid,
          COUNT(*) AS count,
          ST_Centroid(ST_Collect(gg::geometry)) AS center_geom
        FROM cells
        GROUP BY kind, grid
        HAVING COUNT(*) >= :min_count
      ),
      zones AS (
        SELECT
          kind,
          count::int AS count,
          ST_Y(center_geom) AS lat,
          ST_X(center_geom) AS lng
        FROM grouped
      )
      SELECT z.kind, z.count, z.lat, z.lng
      FROM zones z
      WHERE NOT EXISTS (
        SELECT 1
        FROM acks ak
        WHERE LOWER(TRIM(ak.kind::text)) = LOWER(TRIM(z.kind::text))
          AND ST_DWithin(
            (ST_SetSRID(ST_MakePoint(z.lng, z.lat),4326)::geography),
            (ak.geom::geography),
            :ack_r
          )
      )
      ORDER BY z.count DESC
      LIMIT 50
    """)


    params = {
        "kind": k,
        "lng": lng, "lat": lat,
        "rad_m": float(radius_km) * 1000.0,
        "hours": int(hours),
        "cell_deg": float(cell_deg),
        "min_count": int(min_count),
        "ack_r": float(cell_m),
    }

    try:
        rs = await db.execute(sql, params)
        rows = rs.mappings().all()
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"alert_zones failed: {e}")

    return [
        {"kind": r["kind"], "lat": float(r["lat"]), "lng": float(r["lng"]),
         "radius_m": int(cell_m), "count": int(r["count"])}
        for r in rows
    ]



# ---------- PRISE EN CHARGE POMPIER / ADMIN (écriture) ----------
class AckIn(BaseModel):
    kind: str
    lat: float
    lng: float
    user_id: Optional[str] = None    # optionnel: pour traçabilité

@router.post("/fire_ack")
async def fire_ack(
    p: AckIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    # simple auth pompier/admin via x-admin-token (même logique que /admin/*)
    admin_hdr = (request.headers.get("x-admin-token") or "").strip()
    tok = (os.getenv("ADMIN_TOKEN") or os.getenv("NEXT_PUBLIC_ADMIN_TOKEN") or "").strip()
    if not tok or admin_hdr != tok:
        raise HTTPException(status_code=401, detail="invalid admin token")

    k = (p.kind or "").strip().lower()
    if k not in {"traffic","accident","fire","flood","power","water"}:
        raise HTTPException(400, "invalid kind")

    try:
        await db.execute(text("""
            INSERT INTO acks(kind, geom, user_id, created_at)
            VALUES (:k, ST_SetSRID(ST_MakePoint(:lng,:lat),4326)::geography,
                    NULLIF(:uid,'')::uuid, NOW())
        """), {"k": k, "lng": p.lng, "lat": p.lat, "uid": (p.user_id or "")})
        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(500, f"fire_ack failed: {e}")

    return {"ok": True}

