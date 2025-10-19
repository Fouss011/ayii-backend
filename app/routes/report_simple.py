# app/routes/report.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_db
from app.schemas import ReportIn
from app.crud import insert_report

router = APIRouter()

@router.post("/report")
async def create_report(payload: ReportIn, db: AsyncSession = Depends(get_db)):
    try:
        rid = await insert_report(
            db,
            kind=payload.kind.value if hasattr(payload.kind, "value") else str(payload.kind),
            signal=payload.signal.value if hasattr(payload.signal, "value") else str(payload.signal),
            lat=payload.lat,
            lng=payload.lng,
            accuracy_m=int(payload.accuracy_m) if payload.accuracy_m is not None else None,
            note=payload.note,
            photo_url=payload.photo_url,
            user_id=payload.user_id,
        )
        return {"ok": True, "report_id": rid}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
