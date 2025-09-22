"""
Abstraction pour PostgreSQL via asyncpg.

Principes :
- Un pool global unique, créé à la demande (`get_pool`)
- Fonctions utilitaires atomiques (pas d'ORM) pour garder le contrôle
- Schéma minimal centré sur la table `discord_user` (upsert des membres)
"""
from __future__ import annotations

import asyncpg
import logging
from typing import Iterable, Sequence, Tuple

logger = logging.getLogger(__name__)

_pool = None


# Schéma principal minimal pour les utilisateurs Discord
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS discord_user (
    id BIGINT PRIMARY KEY,
    display_name TEXT NOT NULL,
    username TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_discord_user_updated_at ON discord_user(updated_at DESC);
"""


# Upsert idempotent (mise à jour si conflit sur la clé primaire)
UPSERT_USER_SQL = """
INSERT INTO discord_user(id, display_name, username, updated_at)
VALUES($1, $2, $3, NOW())
ON CONFLICT (id) DO UPDATE SET display_name = EXCLUDED.display_name, username = EXCLUDED.username, updated_at = NOW();
"""


async def get_pool(dsn: str):
    """
    Retourne (et crée si nécessaire) le pool asyncpg.
    Args :
        dsn : URL de connexion Postgres
    """
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(dsn, min_size=1, max_size=5)
        logger.info("Pool asyncpg initialisé")
    return _pool


async def ensure_schema(pool: asyncpg.Pool):
    """
    Vérifie et crée le schéma requis si absent.
    """
    async with pool.acquire() as conn:
        await conn.execute(CREATE_TABLE_SQL)
        logger.info("Schéma vérifié (discord_user)")


async def upsert_user(pool: asyncpg.Pool, user_id: int, display_name: str, username: str):
    """
    Insère ou met à jour un utilisateur Discord par son ID.
    """
    async with pool.acquire() as conn:
        await conn.execute(UPSERT_USER_SQL, user_id, display_name, username)


async def bulk_upsert_users(pool: asyncpg.Pool, rows: Iterable[Tuple[int, str, str]]):
    """
    Effectue plusieurs upserts séquentiels dans une transaction.
    Returns : nombre de lignes traitées
    """
    rows_list: Sequence[Tuple[int, str, str]] = list(rows)
    if not rows_list:
        return 0
    async with pool.acquire() as conn:
        async with conn.transaction():
            for uid, display_name, username in rows_list:
                await conn.execute(UPSERT_USER_SQL, uid, display_name, username)
    return len(rows_list)
