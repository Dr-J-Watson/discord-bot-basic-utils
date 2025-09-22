"""
Textes et helpers pour la commande `/sync_users`.
"""
from __future__ import annotations

def build_success(count: int) -> str:
    return f"Sync OK: {count} utilisateurs"

def build_error() -> str:
    return "Erreur sync"

def build_no_db() -> str:
    return "DB non configurée"

__all__ = ["build_success", "build_error", "build_no_db"]