# app/config.py
import os

# URL publique de ton backend (ex: "https://ayii-backend.onrender.com")
BASE_PUBLIC_URL = os.getenv("BASE_PUBLIC_URL", "http://localhost:8000").rstrip("/")

# Dossier local où stocker les images en fallback local (docker/render -> /tmp)
STATIC_DIR = os.getenv("STATIC_DIR", "/tmp/attachments")
os.makedirs(STATIC_DIR, exist_ok=True)

# Chemin URL sous lequel servir ces fichiers
STATIC_URL_PATH = os.getenv("STATIC_URL_PATH", "/static")
