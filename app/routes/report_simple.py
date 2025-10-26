# app/routes/report_simple.py
from typing import Any, Optional
import json

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text  # pour journaliser l'événement "created"

# === Import get_db, tolérant ===
try:
    from app.dependencies import get_db
except Exception:
    try:
        from app.db import get_db
    except Exception as e:
        raise RuntimeError("Impossible d'importer get_db (ni app.dependencies.get_db, ni app.db.get_db).") from e


# Cherche insert_report dans les modules probables
_insert_report = None
for path in ("app.services.reports", "app.core.reports", "app.db.reports", "app.reports"):
    try:
        module = __import__(path, fromlist=["insert_report"])
        _insert_report = getattr(module, "insert_report", None)
        if _insert_report:
            break
    except Exception:
        pass
if _insert_report is None:
    raise RuntimeError("Impossible d'importer insert_report. Corrige l'import ci-dessus.")
insert_report = _insert_report

# Hook d'intégrité (signature HMAC) après insertion
from app.services.report_hooks import enrich_and_sign_report

# Essaie d'utiliser ton modèle ReportIn ; sinon, fallback Pydantic
ReportIn = None
try:
    from app.schemas import ReportIn as _ReportIn
    ReportIn = _ReportIn
except Exception:
    try:
        from app.models.schemas import ReportIn as _ReportIn  # autre emplacement possible
        ReportIn = _ReportIn
    except Exception:
        ReportIn = None

if ReportIn is None:
    from pydantic import BaseModel, Field  # fallback

    class ReportIn(BaseModel):
        kind: str
        signal: str
        lat: float
        lng: float
        accuracy_m: Optional[int] = Field(default=None)
        note: Optional[str] = Field(default=None)
        photo_url: Optional[str] = Field(default=None)
        user_id: Optional[str] = Field(default=None)
        device_id: Optional[str] = Field(default=None)         # ✅ ajouté
        idempotency_key: Optional[str] = Field(default=None)

router = APIRouter()


def _normalize_enum_or_str(v: Any) -> str:
    if v is None:
        return ""
    return getattr(v, "value", v) if not isinstance(v, str) else v


def _deep_unwrap_json_string(value: Any) -> Any:
    """Déshabille récursivement les chaînes JSON : '"{\"a\":1}"' -> '{"a":1}' -> {'a':1}"""
    try:
        v = value
        while isinstance(v, str):
            t = v.strip()
            if t.startswith("{") or t.startswith("["):
                v = json.loads(v)
            else:
                break
        return v
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=422, detail=f"Invalid JSON string: {str(e)}")


@router.post("/report")
async def create_report(payload: Any = Body(...), db: AsyncSession = Depends(get_db)):
    """
    Accepte un body JSON objet **ou** une chaîne JSON (même double/triple stringifié).
    Valide via ReportIn puis appelle insert_report(...), signe le report (HMAC) et journalise l'événement.
    """
    # 1) Déshabille si c'est une string
    payload = _deep_unwrap_json_string(payload)

    # 2) Doit finir en dict
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Input should be a valid JSON object")

    # 3) Validation Pydantic (v2 puis fallback v1)
    try:
        data = ReportIn.model_validate(payload)  # Pydantic v2
    except AttributeError:
        data = ReportIn.parse_obj(payload)       # Compat Pydantic v1
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"validation error: {str(e)}")

    kind = _normalize_enum_or_str(getattr(data, "kind", None))
    signal = _normalize_enum_or_str(getattr(data, "signal", None))

    # 4) Insertion + signature + journal "created"
    try:
        rid = await insert_report(
            db,
            kind=kind,
            signal=signal,
            lat=float(getattr(data, "lat")),
            lng=float(getattr(data, "lng")),
            accuracy_m=int(getattr(data, "accuracy_m", 0)) if getattr(data, "accuracy_m", None) is not None else None,
            note=getattr(data, "note", None),
            photo_url=getattr(data, "photo_url", None),
            user_id=getattr(data, "user_id", None),
            idempotency_key=getattr(data, "idempotency_key", None),
            device_id=getattr(data, "device_id", None),  # ✅ passe device_id si ton insert le supporte
        )

        # 4b) Signature HMAC (intégrité)
        await enrich_and_sign_report(
            db, rid,
            kind=kind, signal=signal,
            lat=float(getattr(data, "lat")), lng=float(getattr(data, "lng")),
            device_id=getattr(data, "device_id", None),
            accuracy_m=int(getattr(data, "accuracy_m", 0)) if getattr(data, "accuracy_m", None) is not None else None,
            photo_url=getattr(data, "photo_url", None),
            user_id=getattr(data, "user_id", None),
        )

        # 4c) Journaliser l'événement "created"
        await db.execute(
            text("INSERT INTO report_events (report_id, event) VALUES (CAST(:rid AS uuid), 'created')"),
            {"rid": rid},
        )
        await db.commit()

        return {"ok": True, "id": rid, "idempotency_key": getattr(data, "idempotency_key", None)}
    except HTTPException:
        raise
    except Exception as e:
        # rollback soft si erreur en cours de route
        try:
            await db.rollback()
        except Exception:
            pass
        raise HTTPException(status_code=400, detail=str(e))
