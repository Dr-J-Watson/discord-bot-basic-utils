"""
Helpers base de données pour la commande `/dbbrowse`.
"""
from __future__ import annotations
import asyncpg
from dataclasses import dataclass, field
from typing import List, Any

@dataclass
class TablePage:
    table: str
    page: int = 0
    page_size: int = 10
    columns: List[str] = field(default_factory=list)
    rows: List[List[Any]] = field(default_factory=list)
    total: int = 0

async def fetch_tables(pool: asyncpg.Pool) -> list[str]:
    q = """SELECT table_name FROM information_schema.tables
           WHERE table_schema='public' AND table_type='BASE TABLE'
           ORDER BY table_name"""
    async with pool.acquire() as conn:
        rows = await conn.fetch(q)
    return [r[0] for r in rows]

async def fetch_page(pool: asyncpg.Pool, table: str, page: int, page_size: int) -> TablePage:
    async with pool.acquire() as conn:
        count_q = f'SELECT COUNT(*) FROM "{table}"'
        total = await conn.fetchval(count_q) or 0
        col_q = """SELECT column_name FROM information_schema.columns
                  WHERE table_schema='public' AND table_name=$1 ORDER BY ordinal_position"""
        col_rows = await conn.fetch(col_q, table)
        columns = [r[0] for r in col_rows]
        offset = page * page_size
        data_q = f'SELECT * FROM "{table}" ORDER BY 1 OFFSET $1 LIMIT $2'
        data_rows = await conn.fetch(data_q, offset, page_size)
    page_obj = TablePage(table=table, page=page, page_size=page_size, columns=columns, total=total)
    for r in data_rows:
        page_obj.rows.append([r[c] for c in columns])
    return page_obj

__all__ = ["fetch_tables", "fetch_page", "TablePage"]
