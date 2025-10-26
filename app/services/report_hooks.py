# app/services/report_hooks.py
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.services.integrity import make_signature

async def enrich_and_sign_report(
    db: AsyncSession,
    report_id: str,
    *,
    kind: str, signal: str, lat: float, lng: float,
    device_id: Optional[str], accuracy_m: Optional[int],
    photo_url: Optional[str], user_id: Optional[str]
) -> None:
    payload = {
        "id": report_id,
        "kind": kind, "signal": signal,
        "lat": round(float(lat), 6),
        "lng": round(float(lng), 6),
        "device_id": device_id or "",
        "accuracy_m": accuracy_m or 0,
        "photo_url": photo_url or "",
        "user_id": user_id or "",
    }
    sig = make_signature(payload)
    q = text("""
        UPDATE reports
        SET signature = :sig
        WHERE id = CAST(:rid AS uuid)
    """)
    await db.execute(q, {"sig": sig, "rid": report_id})
    await db.commit()
