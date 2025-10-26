# app/services/integrity.py
import os, hmac, hashlib, json
from typing import Dict, Any

# Utilise SIGNING_SECRET si présent, sinon ADMIN_TOKEN
SECRET = os.getenv("SIGNING_SECRET") or os.getenv("ADMIN_TOKEN") or "dev-secret"

def canonical(payload: Dict[str, Any]) -> bytes:
    # JSON stable : tri des clés, pas d'espaces
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")

def make_signature(payload: Dict[str, Any]) -> str:
    body = canonical(payload)
    sig = hmac.new(SECRET.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return sig
