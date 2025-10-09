# app/routes/geocode.py
from fastapi import APIRouter, Query
import httpx

router = APIRouter()

@router.get("/reverse")
async def reverse(lat: float = Query(...), lng: float = Query(...)):
    url = "https://nominatim.openstreetmap.org/reverse"
    params = {
        "format": "jsonv2",
        "lat": f"{lat:.6f}",
        "lon": f"{lng:.6f}",
        "accept-language": "fr",
        "zoom": 16
    }
    headers = {
        "User-Agent": "AWO/1.0 (contact: support@awo.local)"
    }
    async with httpx.AsyncClient(timeout=8.0, headers=headers) as client:
        r = await client.get(url, params=params)
        r.raise_for_status()
        j = r.json()
    addr = j.get("address", {})
    label = addr.get("neighbourhood") or addr.get("suburb") or addr.get("city_district") or addr.get("village") or addr.get("town") or addr.get("city") or j.get("display_name", "")
    return {
        "ok": True,
        "label": label,
        "raw": {"display_name": j.get("display_name", ""), "address": addr}
    }
