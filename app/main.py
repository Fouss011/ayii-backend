# app/main.py

from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
import os, re

from app.db import get_db
from app.services.aggregation import run_aggregation

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
            # ouvre proprement une session via get_db()
            agen = get_db()                 # get_db est un async generator
            db = await agen.__anext__()     # récupère une AsyncSession
            try:
                await run_aggregation(db)
            except Exception as e:
                print(f"[scheduler] aggregation error: {e}")
            finally:
                try:
                    await agen.aclose()
                except Exception:
                    pass

        scheduler.add_job(job, trigger=IntervalTrigger(minutes=interval), id="ayii_agg", replace_existing=True)
        scheduler.start()
        print(f"[scheduler] started (every {interval} min)")
    else:
        print("[scheduler] disabled via SCHEDULER_ENABLED=0")

    yield

    # ---- Shutdown ----
    if scheduler.running:
        scheduler.shutdown(wait=False)
        print("[scheduler] stopped")


# Tu peux changer le titre si tu veux
app = FastAPI(title="Ayii API", lifespan=lifespan)

# ---------- CORS ----------

FRONT_ORIGIN = (os.getenv("FRONT_ORIGIN", "https://ayii.netlify.app") or "").strip().rstrip("/")


# Autoriser prod nette + previews Netlify + localhost
NETLIFY_REGEX = r"^https://[a-z0-9-]+(\-\-[a-z0-9-]+)?\.netlify\.app$"

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        FRONT_ORIGIN,                # ex: https://ayii.netlify.app
        "https://ayii.netlify.app",  # garde-fou au cas où FRONT_ORIGIN est mal saisi
        "http://localhost:3000",     # dev local
    ],
    allow_origin_regex=NETLIFY_REGEX,  # couvre deploy-preview-123--... etc.
    allow_credentials=True,            # autorisé car on n'utilise pas "*"
    allow_methods=["GET", "POST", "OPTIONS"],  # explicite
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=86400,
)


# ---------- Health ----------
@app.get("/health")
async def health():
    return {"ok": True}

# ---------- Routes ----------
from app.routes.report import router as report_router
from app.routes.map import router as map_router
from app.routes.dev import router as dev_router
from app.routes.admin import router as admin_router

# optionnels si présents
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

app.include_router(report_router)
app.include_router(map_router)
app.include_router(admin_router)

# 👉 n’activer /dev/* qu’en dev
if os.getenv("ENV", "dev") == "dev":
    app.include_router(dev_router)

# (facultatif) exposer la liste des routes seulement en dev
if os.getenv("ENV", "dev") == "dev":
    @app.get("/__routes")
    async def list_routes():
        return sorted([r.path for r in app.routes])

import hashlib, pathlib, os

def _sha(path):
    p = pathlib.Path(path)
    if not p.exists():
        return None
    return hashlib.sha1(p.read_bytes()).hexdigest()[:12]

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
        }
    }
