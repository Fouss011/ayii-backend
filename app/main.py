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
# ---------- CORS ----------
from fastapi.middleware.cors import CORSMiddleware


# ⚠️ MODE DIAG: ouverture totale pour vérifier le CORS (TEMPORAIRE)
# Quand c'est bon, repasse au bloc "STRICT" en-dessous.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # <- TEMPORAIRE
    allow_credentials=False,      # <- OBLIGATOIRE si "*" (sinon CORS invalide)
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=86400,
)

"""
# ---------- (après validation) MODE STRICT ----------
# Dé-commente ce bloc et supprime le bloc "DIAG" ci-dessus.

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONT_ORIGIN, "https://ayii.netlify.app"],  # prod
    allow_origin_regex=r"^https://[a-z0-9-]+\.netlify\.app$",  # previews
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=86400,
)
"""

# ---------- Health ----------
@app.get("/health")
async def health():
    return {"ok": True}

# ---------- Routes ----------
from app.routes.report import router as report_router
from app.routes.map import router as map_router
from app.routes.dev import router as dev_router

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
