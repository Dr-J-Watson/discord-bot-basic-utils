"""
Helpers base de données pour la commande `/list_users`.

Fonctions principales :
- count_users(pool) -> int
- fetch_users_page(pool, offset, limit)
"""
from __future__ import annotations


async def count_users(pool) -> int:
    async with pool.acquire() as conn:  # type: ignore
        return await conn.fetchval("SELECT COUNT(*) FROM discord_user") or 0


async def fetch_users_page(pool, offset: int, limit: int):
    q = "SELECT id, display_name, username, updated_at FROM discord_user ORDER BY updated_at DESC OFFSET $1 LIMIT $2"
    async with pool.acquire() as conn:  # type: ignore
        return await conn.fetch(q, offset, limit)


__all__ = ["count_users", "fetch_users_page"]