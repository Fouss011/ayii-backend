# app/services/cleanup.py
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

async def cleanup_old_reports(db: AsyncSession, hours: int = 24) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    q = text("""
        WITH del AS (
          DELETE FROM reports
          WHERE created_at < :cutoff
          RETURNING id
        )
        INSERT INTO report_events (report_id, event)
        SELECT id, 'deleted' FROM del
        RETURNING 1
    """)
    res = await db.execute(q, {"cutoff": cutoff})
    await db.commit()
    return res.rowcount or 0
