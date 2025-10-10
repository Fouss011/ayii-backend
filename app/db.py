# app/db.py
import os
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL")  # ex: postgresql+psycopg://...:6543/postgres

# 👉 paramètres anti-stale + petit pool (pgBouncer)
engine = create_async_engine(
    DATABASE_URL,
    pool_size=5,              # petit, stable
    max_overflow=2,           # limiter les pics
    pool_recycle=300,         # recycle connexions >5 min
    pool_pre_ping=True,       # teste la connexion avant usage
    connect_args={
        # côté psycopg3, rien d’exotique nécessaire avec pgBouncer
        # on garde vide; si tu as un CA, tu peux ajouter: "sslmode":"require"
    },
)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

async def get_db():
    async with SessionLocal() as session:
        yield session
