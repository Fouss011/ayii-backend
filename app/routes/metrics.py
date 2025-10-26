# app/routes/metrics.py
from __future__ import annotations
import os
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.db import get_db

router = APIRouter(prefix="/metrics", tags=["Metrics"])

# --- auth admin simple (x-admin-token) ---
def _admin_token() -> str:
    return (os.getenv("ADMIN_TOKEN") or os.getenv("NEXT_PUBLIC_ADMIN_TOKEN") or "").strip()

async def require_admin(request: Request) -> bool:
    tok = _admin_token()
    if not tok:
        raise HTTPException(status_code=401, detail="admin token not configured")
    hdr = (request.headers.get("x-admin-token") or "").strip()
    if hdr != tok:
        raise HTTPException(status_code=401, detail="invalid admin token")
    return True


@router.get("/summary")
async def metrics_summary(
    ok: bool = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    hours: int = Query(24, ge=1, le=720),
):
    """
    Vue d'ensemble (last X hours) :
    - nb reports total
    - nb par kind
    - nb par status (new|confirmed|resolved)
    - temps moyen jusqu'au 'resolved' (si dispo)
    """
    params = {"h": hours}

    # total & par status
    q_tot = text("""
        SELECT COUNT(*)::int AS n_total,
               COUNT(*) FILTER (WHERE COALESCE(status,'new')='new')::int AS n_new,
               COUNT(*) FILTER (WHERE status='confirmed')::int AS n_confirmed,
               COUNT(*) FILTER (WHERE status='resolved')::int AS n_resolved
          FROM reports
         WHERE created_at > NOW() - (:h || ' hours')::interval
    """)
    res_tot = await db.execute(q_tot, params)
    tot = res_tot.mappings().first() or {"n_total":0,"n_new":0,"n_confirmed":0,"n_resolved":0}

    # par kind
    q_kind = text("""
        SELECT kind::text AS kind, COUNT(*)::int AS n
          FROM reports
         WHERE created_at > NOW() - (:h || ' hours')::interval
         GROUP BY 1 ORDER BY 2 DESC
    """)
    rows_kind = (await db.execute(q_kind, params)).mappings().all()

    # temps moyen jusqu'à 'resolved' (approx: on prend le dernier report resolved par (kind, zone ~200m))
    # -> version simple: durée entre premier 'cut' et DERNIER 'resolved' par (same kind, 200m, 24h)
    # Ici on donne une valeur indicative = non calculée finement (optionnel)
    avg_min = None

    return {
        "window_h": hours,
        "total": dict(tot),
        "by_kind": rows_kind,
        "avg_to_resolved_min": avg_min,
        "server_now": datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),
    }


@router.get("/incidents_by_day")
async def metrics_incidents_by_day(
    ok: bool = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    days: int = Query(30, ge=1, le=365),
    kind: Optional[str] = Query(None),
):
    """
    Série temporelle: nombre de reports 'cut' par jour (option: filtrer par kind)
    """
    where = ["LOWER(TRIM(signal::text))='cut'"]
    params: Dict[str, Any] = {"d": days}
    if kind:
        where.append("kind = :k")
        params["k"] = kind

    q = text(f"""
        SELECT date_trunc('day', created_at)::date AS day, COUNT(*)::int AS n
          FROM reports
         WHERE {" AND ".join(where)}
           AND created_at >= NOW() - (:d || ' days')::interval
         GROUP BY 1 ORDER BY 1
    """)
    rows = (await db.execute(q, params)).mappings().all()
    return {"days": days, "kind": kind, "series": rows}


@router.get("/kind_breakdown")
async def metrics_kind_breakdown(
    ok: bool = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    days: int = Query(30, ge=1, le=365),
):
    """
    Répartition par kind (pie)
    """
    q = text("""
        SELECT kind::text AS kind, COUNT(*)::int AS n
          FROM reports
         WHERE created_at >= NOW() - (:d || ' days')::interval
         GROUP BY 1 ORDER BY 2 DESC
    """)
    rows = (await db.execute(q, {"d": days})).mappings().all()
    return {"days": days, "items": rows}
