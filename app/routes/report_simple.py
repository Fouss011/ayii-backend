import json
from typing import Any
from fastapi import Body

@router.post("/report")
async def create_report(payload: Any = Body(...), db: AsyncSession = Depends(get_db)):
    try:
        # 🔧 Accepter les corps "stringifiés"
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                raise HTTPException(status_code=422, detail="Invalid JSON string")
        payload = ReportIn.model_validate(payload)  # re-valider proprement

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
