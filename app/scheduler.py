# app/scheduler.py
import asyncio, os
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from app.db import SessionLocal
from app.services.aggregation import run_aggregation

scheduler: AsyncIOScheduler | None = None

async def _tick():
    # protège contre les re-entrances
    async with SessionLocal() as db:
        await run_aggregation(db)

def start_scheduler():
    global scheduler
    if scheduler and scheduler.running:
        return scheduler

    scheduler = AsyncIOScheduler(
        job_defaults={"coalesce": True, "max_instances": 1},
        timezone=os.getenv("TZ", "UTC"),
    )
    # toutes les 60s
    scheduler.add_job(lambda: asyncio.create_task(_tick()),
                      trigger=IntervalTrigger(seconds=60),
                      id="awo_aggregator", replace_existing=True)
    scheduler.start()
    return scheduler

def stop_scheduler():
    global scheduler
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
        scheduler = None
