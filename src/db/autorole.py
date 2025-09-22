"""
Couche base de données pour la fonctionnalité Autorole.

Schéma :
- autorole_group : id SERIAL, guild_id BIGINT, name TEXT (unique par serveur), multi BOOL, max INT,
  feedback BOOL (envoi d'un message de confirmation),
  linked_message_id BIGINT NULL, channel_id BIGINT NULL, broken BOOL par défaut FALSE
- autorole_item : id SERIAL, group_id INT FK, role_id BIGINT, emoji TEXT NULL, position INT
Des index sont ajoutés pour optimiser les recherches.
"""
from __future__ import annotations

import asyncpg
from typing import Optional, Sequence

SCHEMA = """
CREATE TABLE IF NOT EXISTS autorole_group (
    id SERIAL PRIMARY KEY,
    guild_id BIGINT NOT NULL,
    name TEXT NOT NULL,
    multi BOOLEAN NOT NULL DEFAULT TRUE,
    max INT NOT NULL DEFAULT 0,
    feedback BOOLEAN NOT NULL DEFAULT TRUE,
    button_label TEXT NULL,
    button_style INT NULL,
    linked_message_id BIGINT NULL,
    channel_id BIGINT NULL,
    broken BOOLEAN NOT NULL DEFAULT FALSE,
    UNIQUE(guild_id, name)
);

CREATE TABLE IF NOT EXISTS autorole_item (
    id SERIAL PRIMARY KEY,
    group_id INT NOT NULL REFERENCES autorole_group(id) ON DELETE CASCADE,
    role_id BIGINT NOT NULL,
    emoji TEXT NULL,
    position INT NOT NULL,
    UNIQUE(group_id, role_id),
    UNIQUE(group_id, position)
);

CREATE INDEX IF NOT EXISTS idx_autorole_group_guild ON autorole_group(guild_id);
CREATE INDEX IF NOT EXISTS idx_autorole_item_group ON autorole_item(group_id);
"""

async def ensure_schema(pool: asyncpg.Pool):
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(SCHEMA)
            # Migrations idempotentes pour colonnes ajoutées après coup
            await conn.execute("ALTER TABLE autorole_group ADD COLUMN IF NOT EXISTS feedback BOOLEAN NOT NULL DEFAULT TRUE")
            await conn.execute("ALTER TABLE autorole_group ADD COLUMN IF NOT EXISTS button_label TEXT NULL")
            await conn.execute("ALTER TABLE autorole_group ADD COLUMN IF NOT EXISTS button_style INT NULL")

# Groups
async def create_group(pool: asyncpg.Pool, guild_id: int, name: str, multi: bool = True, max_value: int = 0, feedback: bool = True,
                       button_label: Optional[str] = None, button_style: Optional[int] = None) -> asyncpg.Record:
    q = """
    INSERT INTO autorole_group(guild_id, name, multi, max, feedback, button_label, button_style)
    VALUES($1,$2,$3,$4,$5,$6,$7)
        ON CONFLICT (guild_id, name) DO NOTHING
        RETURNING *
    """
    async with pool.acquire() as conn:
        return await conn.fetchrow(q, guild_id, name, multi, max_value, feedback, button_label, button_style)

async def get_group(pool: asyncpg.Pool, guild_id: int, name: str) -> Optional[asyncpg.Record]:
    q = "SELECT * FROM autorole_group WHERE guild_id=$1 AND name=$2"
    async with pool.acquire() as conn:
        return await conn.fetchrow(q, guild_id, name)

async def get_group_by_id(pool: asyncpg.Pool, group_id: int) -> Optional[asyncpg.Record]:
    q = "SELECT * FROM autorole_group WHERE id=$1"
    async with pool.acquire() as conn:
        return await conn.fetchrow(q, group_id)

async def list_groups(pool: asyncpg.Pool, guild_id: int) -> Sequence[asyncpg.Record]:
    q = "SELECT * FROM autorole_group WHERE guild_id=$1 ORDER BY name"
    async with pool.acquire() as conn:
        return await conn.fetch(q, guild_id)

async def update_group(pool: asyncpg.Pool, group_id: int, *, multi: Optional[bool] = None, max_value: Optional[int] = None,
                       linked_message_id: Optional[int] = None, channel_id: Optional[int] = None, broken: Optional[bool] = None,
                       feedback: Optional[bool] = None,
                       button_label: Optional[str] = None, button_style: Optional[int] = None):
    q = """
        UPDATE autorole_group SET
            multi = COALESCE($2, multi),
            max = COALESCE($3, max),
            linked_message_id = COALESCE($4, linked_message_id),
            channel_id = COALESCE($5, channel_id),
            broken = COALESCE($6, broken),
            feedback = COALESCE($7, feedback),
            button_label = COALESCE($8, button_label),
            button_style = COALESCE($9, button_style)
        WHERE id=$1
        RETURNING *
    """
    async with pool.acquire() as conn:
        return await conn.fetchrow(q, group_id, multi, max_value, linked_message_id, channel_id, broken, feedback, button_label, button_style)

async def delete_group(pool: asyncpg.Pool, guild_id: int, name: str):
    q = "DELETE FROM autorole_group WHERE guild_id=$1 AND name=$2"
    async with pool.acquire() as conn:
        await conn.execute(q, guild_id, name)

# Items
async def list_items(pool: asyncpg.Pool, group_id: int) -> Sequence[asyncpg.Record]:
    q = "SELECT * FROM autorole_item WHERE group_id=$1 ORDER BY position"
    async with pool.acquire() as conn:
        return await conn.fetch(q, group_id)

async def add_item(pool: asyncpg.Pool, group_id: int, role_id: int, emoji: Optional[str], position: Optional[int] = None) -> asyncpg.Record:
    async with pool.acquire() as conn:
        async with conn.transaction():
            pos = position
            if pos is None:
                pos = await conn.fetchval("SELECT COALESCE(MAX(position),0)+1 FROM autorole_item WHERE group_id=$1", group_id) or 1
            q = """
                INSERT INTO autorole_item(group_id, role_id, emoji, position)
                VALUES($1,$2,$3,$4)
                RETURNING *
            """
            return await conn.fetchrow(q, group_id, role_id, emoji, pos)

async def remove_item_by_role(pool: asyncpg.Pool, group_id: int, role_id: int):
    q = "DELETE FROM autorole_item WHERE group_id=$1 AND role_id=$2"
    async with pool.acquire() as conn:
        await conn.execute(q, group_id, role_id)

async def remove_item_by_emoji(pool: asyncpg.Pool, group_id: int, emoji: str):
    q = "DELETE FROM autorole_item WHERE group_id=$1 AND emoji=$2"
    async with pool.acquire() as conn:
        await conn.execute(q, group_id, emoji)

async def get_group_by_message(pool: asyncpg.Pool, channel_id: int, message_id: int) -> Optional[asyncpg.Record]:
    q = "SELECT * FROM autorole_group WHERE channel_id=$1 AND linked_message_id=$2"
    async with pool.acquire() as conn:
        return await conn.fetchrow(q, channel_id, message_id)
