# app/main.py
from contextlib import asynccontextmanager
import hashlib
import os
import pathlib

from dotenv import load_dotenv
from fastapi import FastAPI, Response, Request
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.db import get_db
from app.services.aggregation import run_aggregation

# Charger .env en local (hors Render)
if os.getenv("RENDER") is None and os.getenv("ENV", "dev") == "dev":
    load_dotenv()

scheduler = AsyncIOScheduler()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ---- Startup ----
    enable = os.getenv("SCHEDULER_ENABLED", "1") != "0"
    if enable:
        interval = int(os.getenv("AGG_INTERVAL_MIN", "2"))

        async def job():
            agen = get_db()                 # async generator
            db = await agen.__anext__()     # AsyncSession
            try:
                await run_aggregation(db)
            except Exception as e:
                print(f"[scheduler] aggregation error: {e}")
            finally:
                try:
                    await agen.aclose()
                except Exception:
                    pass

        scheduler.add_job(
            job,
            trigger=IntervalTrigger(minutes=interval),
            id="ayii_agg",
            replace_existing=True,
        )
        scheduler.start()
        print(f"[scheduler] started (every {interval} min)")
    else:
        print("[scheduler] disabled via SCHEDULER_ENABLED=0")

    yield

    # ---- Shutdown ----
    if scheduler.running:
        scheduler.shutdown(wait=False)
        print("[scheduler] stopped")


app = FastAPI(title="Ayii API", lifespan=lifespan)

# debug token admin (masqué)
tok = (os.getenv("ADMIN_TOKEN") or os.getenv("NEXT_PUBLIC_ADMIN_TOKEN") or "").strip()
print(f"[admin-token] len={len(tok)} head={tok[:4]} tail={tok[-4:]}")

# ---------- CORS ----------
FRONT_ORIGIN = (os.getenv("FRONT_ORIGIN", "https://ayii.netlify.app") or "").strip().rstrip("/")
NETLIFY_REGEX = r"^https://[a-z0-9-]+(\-\-[a-z0-9-]+)?\.netlify\.app$"

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://ayii.netlify.app","http://localhost:3000"],
    allow_origin_regex=r"^https://[a-z0-9-]+(\-\-[a-z0-9-]+)?\.netlify\.app$",
    allow_credentials=False,      # pas de cookies
    allow_methods=["GET","POST","OPTIONS"],
    allow_headers=["Content-Type","x-admin-token"],
    expose_headers=[],
    max_age=86400,
)

# ---------- Health ----------
@app.get("/health")
async def health():
    return {"ok": True}

# ---------- Routes ----------
from app.routes.map import router as map_router
from app.routes.dev import router as dev_router

# Optionnels si présents (protégés par try pour éviter durs imports)
try:
    from app.routes.reverse import router as reverse_router
    app.include_router(reverse_router)
except Exception:
    pass

try:
    from app.routes.outages import router as outages_router
    app.include_router(outages_router)
except Exception:
    pass

# Router principal (contient /map, /report, /reset_user, etc.)
app.include_router(map_router)

# n’activer /dev/* qu’en dev
if os.getenv("ENV", "dev") == "dev":
    app.include_router(dev_router)

# (facultatif) exposer la liste des routes et versions seulement en dev
def _sha(path: str):
    p = pathlib.Path(path)
    if not p.exists():
        return None
    return hashlib.sha1(p.read_bytes()).hexdigest()[:12]

if os.getenv("ENV", "dev") == "dev":
    @app.get("/__routes")
    async def list_routes():
        return sorted([r.path for r in app.routes])

    @app.get("/__version")
    async def version():
        return {
            "ENV": os.getenv("ENV"),
            "SCHEDULER_ENABLED": os.getenv("SCHEDULER_ENABLED"),
            "AGG_INTERVAL_MIN": os.getenv("AGG_INTERVAL_MIN"),
            "files": {
                "aggregation.py": _sha("app/services/aggregation.py"),
                "crud.py": _sha("app/crud.py"),
                "db.py": _sha("app/db.py"),
                "main.py": _sha("app/main.py"),
            },
        }

# no-store pour /map (évite cache côté CDN/navigateur)
@app.middleware("http")
async def no_store_cache(request: Request, call_next):
    response: Response = await call_next(request)
    if request.url.path == "/map":
        response.headers["Cache-Control"] = "no-store"
    return response
