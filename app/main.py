# app/main.py
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.services.aggregation import run_aggregation
from app.db import get_db  # async dependency

scheduler = AsyncIOScheduler()

@asynccontextmanager
async def lifespan(app: FastAPI):
    enable = os.getenv("SCHEDULER_ENABLED", "1") != "0"
    if enable:
        interval = int(os.getenv("AGG_INTERVAL_MIN", "2"))

        async def job():
            agen = get_db()
            db = await agen.__anext__()
            try:
                await run_aggregation(db)
            except Exception as e:
                print(f"[scheduler] aggregation error: {e}")
            finally:
                try:
                    await agen.aclose()
                except Exception:
                    pass

        scheduler.add_job(job, trigger=IntervalTrigger(minutes=interval))
        scheduler.start()
        print(f"[scheduler] started (every {interval} min)")
    else:
        print("[scheduler] disabled via SCHEDULER_ENABLED=0")
    yield
    if scheduler.running:
        scheduler.shutdown(wait=False)
        print("[scheduler] stopped")

# ✅ debug=True pour voir la stacktrace dans le navigateur
app = FastAPI(title="Awo API", debug=True, lifespan=lifespan)

# ✅ CORS DEV large
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Health
@app.get("/health")
async def health():
    return {"ok": True}

# Routes
from app.routes.report import router as report_router
from app.routes.map import router as map_router
from app.routes.dev import router as dev_router

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
app.include_router(dev_router)
