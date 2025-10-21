# app/routes/report_simple.py
from typing import Any, Optional
import json

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

# ⚙️ Adapte ces imports à ton projet.
# On essaie plusieurs chemins possibles pour éviter de casser ton arborescence existante.
try:
    from app.dependencies import get_db  # ton get_db existant
except Exception as e:
    raise RuntimeError("Impossible d'importer get_db depuis app.dependencies. Adapte l'import.") from e

# insert_report: logiques d'insertion/traitement existantes
_insert_report = None
for path in (
    "app.services.reports",
    "app.core.reports",
    "app.db.reports",
    "app.reports",
):
    try:
        module = __import__(path, fromlist=["insert_report"])
        _insert_report = getattr(module, "insert_report", None)
        if _insert_report:
            break
    except Exception:
        pass
if _insert_report is None:
    raise RuntimeError(
        "Impossible d'importer insert_report. Adapte l'import en haut du fichier "
        "pour pointer vers ta fonction d'insertion."
    )
insert_report = _insert_report

# ✅ Modèle d'entrée : on privilégie ton modèle existant si présent
ReportIn = None
try:
    from app.schemas import ReportIn as _ReportIn  # ajuste si nécessaire
    ReportIn = _ReportIn
except Exception:
    try:
        from app.models.schemas import ReportIn as _ReportIn  # autre emplacement possible
        ReportIn = _ReportIn
    except Exception:
        ReportIn = None

# Fallback Pydantic minimal si ton ReportIn n'est pas importable
if ReportIn is None:
    try:
        from pydantic import BaseModel, Field
    except Exception as e:
        raise RuntimeError("Pydantic est requis pour le fallback ReportIn") from e

    class ReportIn(BaseModel):
        kind: str
        signal: str
        lat: float
        lng: float
        accuracy_m: Optional[int] = Field(default=None)
        note: Optional[str] = Field(default=None)
        photo_url: Optional[str] = Field(default=None)
        user_id: Optional[str] = Field(default=None)
        idempotency_key: Optional[str] = Field(default=None)

router = APIRouter()


def _normalize_enum_or_str(v: Any) -> str:
    """Retourne la valeur string d'un champ qui peut être un Enum ou str."""
    if v is None:
        return ""
    # Pydantic v2 Enum => .value ; sinon, cast en str
    return getattr(v, "value", v) if not isinstance(v, str) else v


def _deep_unwrap_json_string(value: Any) -> Any:
    """
    Déshabille récursivement les chaînes JSON :
    '"{\"a\":1}"' -> '{"a":1}' -> {'a':1}
    """
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
async def create_report(
    payload: Any = Body(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Hotfix: accepte un body JSON objet OU une chaîne JSON (même double/triple-stringifié).
    Revalide via ReportIn (ton modèle) puis exécute insert_report(...).
    """
    # 1) Déshabillage récursif si c'est une string
    payload = _deep_unwrap_json_string(payload)

    # 2) Doit être un dict au final
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="Input should be a valid JSON object")

    # 3) Validation via ton modèle Pydantic
    try:
        data = ReportIn.model_validate(payload)  # Pydantic v2
    except AttributeError:
        # Compat Pydantic v1 si besoin
        try:
            data = ReportIn.parse_obj(payload)  # type: ignore[attr-defined]
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"validation error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"validation error: {str(e)}")

    kind = _normalize_enum_or_str(getattr(data, "kind", None))
    signal = _normalize_enum_or_str(getattr(data, "signal", None))

    # 4) Appel de ta logique métier existante
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
        )
        return {
            "ok": True,
            "id": rid,
            "idempotency_key": getattr(data, "idempotency_key", None),
        }
    except HTTPException:
        raise
    except Exception as e:
        # Renvoie 400 générique pour erreurs métier internes
        raise HTTPException(status_code=400, detail=str(e))
