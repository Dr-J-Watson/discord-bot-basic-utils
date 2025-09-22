"""
Helpers base de données pour la fonctionnalité voice hubs.
"""
from __future__ import annotations
import asyncpg
from typing import Optional, Sequence

VOICE_HUB_SCHEMA = """
CREATE TABLE IF NOT EXISTS voice_hub (
    id BIGINT PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    naming_scheme TEXT NULL,
    max_rooms INT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS voice_room (
    id BIGINT PRIMARY KEY,
    hub_id BIGINT NOT NULL REFERENCES voice_hub(id) ON DELETE CASCADE,
    guild_id BIGINT NOT NULL,
    creator_id BIGINT NULL,
    sequence INT NOT NULL,
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_voice_room_hub ON voice_room(hub_id);
CREATE INDEX IF NOT EXISTS idx_voice_hub_guild ON voice_hub(guild_id);
"""

async def ensure_voice_hub_schema(pool: asyncpg.Pool):
    async with pool.acquire() as conn:
        await conn.execute(VOICE_HUB_SCHEMA)

async def insert_hub(pool: asyncpg.Pool, channel_id: int, guild_id: int):
    q = """INSERT INTO voice_hub(id, guild_id) VALUES($1,$2)
            ON CONFLICT (id) DO UPDATE SET updated_at = NOW(), active = TRUE
            RETURNING id, guild_id, active, naming_scheme, max_rooms"""
    async with pool.acquire() as conn:
        return await conn.fetchrow(q, channel_id, guild_id)

async def deactivate_hub(pool: asyncpg.Pool, channel_id: int):
    q = "UPDATE voice_hub SET active = FALSE, updated_at = NOW() WHERE id=$1"
    async with pool.acquire() as conn:
        await conn.execute(q, channel_id)

async def fetch_active_hubs(pool: asyncpg.Pool) -> Sequence[asyncpg.Record]:
    q = "SELECT id, guild_id, naming_scheme, max_rooms FROM voice_hub WHERE active=TRUE"
    async with pool.acquire() as conn:
        return await conn.fetch(q)

async def hub_exists(pool: asyncpg.Pool, channel_id: int) -> bool:
    q = "SELECT 1 FROM voice_hub WHERE id=$1 AND active=TRUE"
    async with pool.acquire() as conn:
        return await conn.fetchval(q, channel_id) is not None

async def update_hub_config(pool: asyncpg.Pool, channel_id: int, naming_scheme: str | None, user_limit: int | None):
    q = """
        UPDATE voice_hub
        SET
            naming_scheme = COALESCE($2, naming_scheme),
            max_rooms = COALESCE($3, max_rooms),
            updated_at = NOW()
        WHERE id=$1
        RETURNING id, naming_scheme, max_rooms
    """
    async with pool.acquire() as conn:
        return await conn.fetchrow(q, channel_id, naming_scheme, user_limit)

async def fetch_hub_config(pool: asyncpg.Pool, channel_id: int):
    q = "SELECT id, naming_scheme, max_rooms FROM voice_hub WHERE id=$1"
    async with pool.acquire() as conn:
        return await conn.fetchrow(q, channel_id)

async def insert_room(pool: asyncpg.Pool, room_id: int, hub_id: int, guild_id: int, creator_id: Optional[int], sequence: int, name: str):
    q = """INSERT INTO voice_room(id, hub_id, guild_id, creator_id, sequence, name)
            VALUES($1,$2,$3,$4,$5,$6) RETURNING id"""
    async with pool.acquire() as conn:
        return await conn.fetchval(q, room_id, hub_id, guild_id, creator_id, sequence, name)

async def delete_room(pool: asyncpg.Pool, room_id: int):
    q = "DELETE FROM voice_room WHERE id=$1"
    async with pool.acquire() as conn:
        await conn.execute(q, room_id)

async def fetch_room(pool: asyncpg.Pool, room_id: int):
    q = "SELECT id, hub_id FROM voice_room WHERE id=$1"
    async with pool.acquire() as conn:
        return await conn.fetchrow(q, room_id)

async def count_rooms_for_hub(pool: asyncpg.Pool, hub_id: int) -> int:
    q = "SELECT COUNT(*) FROM voice_room WHERE hub_id=$1"
    async with pool.acquire() as conn:
        return await conn.fetchval(q, hub_id) or 0

async def next_sequence_for_hub(pool: asyncpg.Pool, hub_id: int) -> int:
    # Retourne le plus petit entier positif manquant (1..max+1) pour combler les trous de numérotation
    q = """
        WITH maxseq AS (
            SELECT COALESCE(MAX(sequence), 0) AS maxs
            FROM voice_room
            WHERE hub_id = $1
        ), series AS (
            SELECT generate_series(1, (SELECT maxs FROM maxseq) + 1) AS s
        )
        SELECT COALESCE(
            (
                SELECT MIN(s) FROM series
                WHERE NOT EXISTS (
                    SELECT 1 FROM voice_room vr
                    WHERE vr.hub_id = $1 AND vr.sequence = series.s
                )
            ),
            1
        ) AS next_seq
    """
    async with pool.acquire() as conn:
        return await conn.fetchval(q, hub_id) or 1

async def fetch_all_rooms(pool: asyncpg.Pool):
    q = "SELECT id, hub_id FROM voice_room"
    async with pool.acquire() as conn:
        return await conn.fetch(q)

__all__ = [
    "ensure_voice_hub_schema","insert_hub","deactivate_hub","fetch_active_hubs","hub_exists","update_hub_config",
    "fetch_hub_config","insert_room","delete_room","fetch_room","count_rooms_for_hub","next_sequence_for_hub","fetch_all_rooms"
]