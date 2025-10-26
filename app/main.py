# app/main.py
import os
import pathlib
import hashlib
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.staticfiles import StaticFiles

# Scheduler (facultatif)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

# Config & services internes
from app.config import STATIC_DIR, STATIC_URL_PATH           # constants (pas d'app ici)
from app.db import get_db                                   # async session factory
from app.services.aggregation import run_aggregation        # ta tâche d’agrégation

# ⚠️ NE PAS inclure de router ici (app pas encore créée)

# -----------------------------------------------------------------------------
# Chargement .env en local (pas sur Render/Prod)
# -----------------------------------------------------------------------------
if os.getenv("RENDER") is None and os.getenv("ENV", "dev") == "dev":
    load_dotenv()

# -----------------------------------------------------------------------------
# Lifespan avec scheduler optionnel
# -----------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- Startup ---
    enable = os.getenv("SCHEDULER_ENABLED", "1") != "0"
    scheduler = None

    if enable:
        interval = int(os.getenv("AGG_INTERVAL_MIN", "2"))
        scheduler = AsyncIOScheduler()

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

    # Rendez le scheduler accessible si besoin
    app.state.scheduler = scheduler

    yield

    # --- Shutdown ---
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
        print("[scheduler] stopped")


# -----------------------------------------------------------------------------
# App
# -----------------------------------------------------------------------------
app = FastAPI(title="Ayii API", lifespan=lifespan)

# Debug token admin (masqué)
tok = (os.getenv("ADMIN_TOKEN") or os.getenv("NEXT_PUBLIC_ADMIN_TOKEN") or "").strip()
print(f"[admin-token] len={len(tok)} head={tok[:4]} tail={tok[-4:]}")

# -----------------------------------------------------------------------------
# CORS (IMPORTANT: avant d'inclure les routers)
# -----------------------------------------------------------------------------
allowed_origins = {
    "https://ayii.netlify.app",
    "http://localhost:3000",
}

# Surcharge via ALLOWED_ORIGINS="https://foo.netlify.app,https://bar.com"
extra = (os.getenv("ALLOWED_ORIGINS") or "").strip()
if extra:
    for o in extra.split(","):
        o = o.strip()
        if o:
            allowed_origins.add(o)

# Autoriser aussi les Deploy Previews Netlify (regex)
NETLIFY_REGEX = r"^https://[a-z0-9-]+(\-\-[a-z0-9-]+)?\.netlify\.app$"

app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(list(allowed_origins)),
    allow_origin_regex=NETLIFY_REGEX,
    allow_credentials=False,              # pas de cookies cross-site
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
    max_age=86400,
)

# -----------------------------------------------------------------------------
# Fichiers statiques (pour servir les images locales uploadées)
# -----------------------------------------------------------------------------
# Exemple: http(s)://<backend>/static/<filename>.jpg
app.mount(STATIC_URL_PATH, StaticFiles(directory=STATIC_DIR), name="static")

# -----------------------------------------------------------------------------
# Health
# -----------------------------------------------------------------------------
@app.get("/health")
async def health():
    return {"ok": True}

# -----------------------------------------------------------------------------
# Dev helpers (uniquement en ENV=dev)
# -----------------------------------------------------------------------------
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

# -----------------------------------------------------------------------------
# no-store pour /map (éviter cache navigateur/CDN)
# -----------------------------------------------------------------------------
@app.middleware("http")
async def no_store_cache(request: Request, call_next):
    response: Response = await call_next(request)
    if request.url.path == "/map":
        response.headers["Cache-Control"] = "no-store"
    return response

# -----------------------------------------------------------------------------
# Routes (IMPORTER APRÈS la config ci-dessus)
# -----------------------------------------------------------------------------
from app.routes.map import router as map_router         # noqa: E402
app.include_router(map_router)

# Route de report (si séparée)
try:
    from app.routes.report_simple import router as report_router  # noqa: E402
    app.include_router(report_router)
except Exception:
    pass

# CTA séparé (protégé par x-admin-token) — ⚠️ inclure après app = FastAPI(...)
try:
    from app.routes.admin_cta import router as cta_router         # noqa: E402
    app.include_router(cta_router)
except Exception:
    pass

# /dev/* uniquement en dev
try:
    if os.getenv("ENV", "dev") == "dev":
        from app.routes.dev import router as dev_router            # noqa: E402
        app.include_router(dev_router)
except Exception:
    pass

# Optionnels si présents
for opt in ("reverse", "outages"):
    try:
        mod = __import__(f"app.routes.{opt}", fromlist=["router"])
        app.include_router(getattr(mod, "router"))
    except Exception:
        pass
