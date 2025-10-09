# app/routes/map.py
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_db
from app.crud import get_outages_in_radius

router = APIRouter()

@router.get("/map")
async def map_endpoint(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    radius_km: float = Query(5.0, gt=0, le=100),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await get_outages_in_radius(db, lat, lng, radius_km)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
