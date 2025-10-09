# app/routes/outage_label.py
from fastapi import APIRouter, HTTPException, Path, Body, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_db

router = APIRouter()

@router.post("/outages/{outage_id}/label")
async def set_outage_label(
    outage_id: str = Path(...),
    payload: dict = Body(...),
    db: AsyncSession = Depends(get_db)
):
    label = (payload or {}).get("label", "").strip()
    if len(label) == 0:
        raise HTTPException(status_code=400, detail="label requis")
    q = text("UPDATE outages SET label_override=:label WHERE id::text=:id")
    await db.execute(q, {"label": label, "id": outage_id})
    await db.commit()
    return {"ok": True, "outage_id": outage_id, "label": label}
