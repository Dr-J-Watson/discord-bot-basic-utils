"""
Helpers base de données pour la fonctionnalité Welcome (salon de bienvenue par serveur).

Schéma :
- welcome_config : guild_id BIGINT PRIMARY KEY, channel_id BIGINT NOT NULL, updated_at TIMESTAMPTZ DEFAULT NOW()
"""
from __future__ import annotations

import asyncpg
from typing import Optional


SCHEMA = """
CREATE TABLE IF NOT EXISTS welcome_config (
    guild_id BIGINT PRIMARY KEY,
    channel_id BIGINT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


async def ensure_schema(pool: asyncpg.Pool):
    async with pool.acquire() as conn:
        await conn.execute(SCHEMA)


async def set_welcome_channel(pool: asyncpg.Pool, guild_id: int, channel_id: int):
    q = """
    INSERT INTO welcome_config(guild_id, channel_id, updated_at)
    VALUES($1,$2,NOW())
    ON CONFLICT (guild_id) DO UPDATE SET channel_id = EXCLUDED.channel_id, updated_at = NOW()
    """
    async with pool.acquire() as conn:
        await conn.execute(q, guild_id, channel_id)


async def get_welcome_channel(pool: asyncpg.Pool, guild_id: int) -> Optional[int]:
    q = "SELECT channel_id FROM welcome_config WHERE guild_id=$1"
    async with pool.acquire() as conn:
        val = await conn.fetchval(q, guild_id)
        return int(val) if val is not None else None


async def clear_welcome_channel(pool: asyncpg.Pool, guild_id: int):
    q = "DELETE FROM welcome_config WHERE guild_id=$1"
    async with pool.acquire() as conn:
        await conn.execute(q, guild_id)
