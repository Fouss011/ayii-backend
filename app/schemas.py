# app/schemas.py (extrait)
from enum import Enum
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

class ReportKind(str, Enum):
    power = "power"
    water = "water"
    accident = "accident"
    traffic = "traffic"
    fire = "fire"
    flood = "flood"

class ReportSignal(str, Enum):
    cut = "cut"
    restored = "restored"

class ReportIn(BaseModel):
    kind: ReportKind
    signal: ReportSignal
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)
    accuracy_m: Optional[float] = None
    note: Optional[str] = None
    photo_url: Optional[str] = None
    user_id: Optional[str] = None

class ReportOut(BaseModel):
    id: str
    kind: ReportKind
    signal: ReportSignal
    lat: float
    lng: float
    created_at: datetime
    user_id: Optional[str] = None   # ✅
