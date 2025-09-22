"""
Textes et helpers pour les commandes `/hub` (voice hubs).
"""
from __future__ import annotations

def fmt_hub_list_line(channel_id: int, name: str | None) -> str:
    return f"`{channel_id}` {name if name else '(inconnu)'}"

def msg_no_hub() -> str: return "Aucun hub."
def msg_channel_invalide() -> str: return "Channel invalide."
def msg_deja_hub() -> str: return "Déjà hub."
def msg_hub_ajoute(name: str, cid: int) -> str: return f"Hub ajouté: {name} ({cid})"
def msg_pas_un_hub() -> str: return "Pas un hub."
def msg_hub_desactive(name: str) -> str: return f"Hub désactivé: {name}"
def msg_pattern_trop_long() -> str: return "Pattern trop long (max 100)."
def msg_pattern_placeholders() -> str: return "Placeholders inconnus. Autorisés: {user} {display} {n}"
def msg_limite_invalide() -> str: return "Limite invalide (0-99)."

def msg_config_update(parts: list[str]) -> str:
    return " | ".join(parts)

__all__ = [name for name in globals().keys() if name.startswith('msg_') or name.startswith('fmt_')]