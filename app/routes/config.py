# app/config.py
import os
from pathlib import Path

# URL publique de ton backend (sans / final). Ex: https://ayii-backend.onrender.com
BASE_PUBLIC_URL = os.getenv("BASE_PUBLIC_URL", os.getenv("RENDER_EXTERNAL_URL", "")).rstrip("/")

# Chemin disque où servir les images statiques (doit exister et être lisible par l’app)
# En production sur Render, un chemin persistant typique est /opt/render/project/src/static
STATIC_DIR = os.getenv("STATIC_DIR", "/opt/render/project/src/static")
Path(STATIC_DIR).mkdir(parents=True, exist_ok=True)

# Chemin URL pour exposer STATIC_DIR
STATIC_URL_PATH = os.getenv("STATIC_URL_PATH", "/static")
