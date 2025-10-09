from fastapi import APIRouter

router = APIRouter()

@router.post("/subscribe")
async def subscribe():
    # MVP: à brancher plus tard (Web Push / SMS)
    return {"ok": True}
