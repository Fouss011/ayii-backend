# app/routes/admin.py
import os
from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from app.db import get_db
from app.services.aggregation import run_aggregation

router = APIRouter(prefix="/admin", tags=["admin"])

async def _check_token(x_token: str = Header(None)):
    """
    Simple garde : compare l’en-tête X-Token à ADMIN_TOKEN (ou à défaut NEXT_PUBLIC_ADMIN_TOKEN).
    """
    expected = os.getenv("ADMIN_TOKEN") or os.getenv("NEXT_PUBLIC_ADMIN_TOKEN")
    if not expected:  # si aucun token défini, on n’exige rien (en dev)
        return True
    if not x_token or x_token.strip() != expected.strip():
        raise HTTPException(status_code=401, detail="Invalid token")
    return True

@router.post("/reset_user")
async def reset_user(payload: dict,
                     db: AsyncSession = Depends(get_db),
                     _=Depends(_check_token)):
    user_id = (payload or {}).get("user_id", "").strip()
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id requis")

    # 1) Supprimer tous les reports de cet utilisateur
    await db.execute(text("DELETE FROM reports WHERE user_id = :uid"), {"uid": user_id})

    # 2) Optionnel : fermer les outages devenus vides (plus de reports autour)
    #    (Si ta colonne 'center' et 'radius_m' existent comme dans l'agg, sinon retire ce bloc)
    await db.execute(text("""
        UPDATE outages o
           SET status='restored',
               restored_at = COALESCE(restored_at, NOW())
         WHERE o.status='ongoing'
           AND NOT EXISTS (
             SELECT 1
               FROM reports r
              WHERE r.kind::text = o.kind::text
                AND ST_DWithin(r.geom::geography, o.center, o.radius_m)
           )
    """))

    await db.commit()

    # 3) Recalculer l’agrégation (fermetures TTL / reopen, etc.)
    await run_aggregation(db)

    return {"ok": True, "user_id": user_id}

# (Facultatif) Reset global de dev
@router.post("/reset_all")
async def reset_all(db: AsyncSession = Depends(get_db), _=Depends(_check_token)):
    await db.execute(text("TRUNCATE TABLE reports RESTART IDENTITY CASCADE"))
    await db.execute(text("TRUNCATE TABLE outages RESTART IDENTITY CASCADE"))
    await db.execute(text("TRUNCATE TABLE incidents RESTART IDENTITY CASCADE"))
    await db.commit()
    return {"ok": True}
