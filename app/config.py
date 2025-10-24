# app/config.py
import os

# URL publique de ton backend (ex: https://api.tondomaine.com)
BASE_PUBLIC_URL = os.getenv("BASE_PUBLIC_URL", "http://localhost:8000").rstrip("/")

# Dossier local où stocker les pièces jointes quand on n’utilise pas Supabase/S3
STATIC_DIR = os.getenv("STATIC_DIR", "/tmp/attachments")
os.makedirs(STATIC_DIR, exist_ok=True)

# Chemin URL où le backend sert ces fichiers locaux
STATIC_URL_PATH = "/static"
