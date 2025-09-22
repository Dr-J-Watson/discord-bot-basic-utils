"""
Helpers base de données pour la commande `/sync_users`.
"""
from __future__ import annotations
from typing import Iterable, Tuple

async def bulk_upsert_users(pool, rows: Iterable[Tuple[int, str, str]]):
    # Délégué à core.db.bulk_upsert_users pour conserver logique existante
    from core import db as core_db  # import local pour éviter cycles
    return await core_db.bulk_upsert_users(pool, rows)

__all__ = ["bulk_upsert_users"]