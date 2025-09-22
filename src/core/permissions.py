"""
Utilitaires pour la vérification des permissions Discord via bitmask.

Rappel :
- `discord.Permissions` expose un attribut `.value` (int) contenant les bits cumulés
- On teste un sous-ensemble via : (current & required) == required

Exemple : Administrator = 0x00000008

Ce module fournit le décorateur `require_perms` pour les commandes slash.
"""
from __future__ import annotations

from typing import Callable, TypeVar, Awaitable, Any
import functools
import discord

T = TypeVar("T", bound=Callable[..., Awaitable[Any]])

# Extraits de `discord.Permissions` (compléter si besoin futur)
ADMINISTRATOR = 0x00000008


def require_perms(bits: int, *, ephemeral: bool = True, message: str | None = None):
    """
    Décorateur pour vérifier qu'un utilisateur possède toutes les permissions spécifiées (bitmask).

    Args :
        bits : Masque de bits des permissions requises (ex : ADMINISTRATOR = 8)
        ephemeral : Si True, les messages d'erreur sont envoyés en éphémère
        message : Message d'erreur personnalisé (optionnel)

    Fonctionnement :
    - Récupère le bitfield complet via `interaction.user.guild_permissions.value`
    - Vérifie que tous les bits demandés sont présents
    - Si échec : réponse (ou followup) et retour sans exécuter la fonction décorée

    Note :
    - Ce décorateur suppose que la commande s'exécute dans une guild
    - Si utilisée en DM, l'accès est refusé
    """
    def decorator(func: T) -> T:
        @functools.wraps(func)
        async def wrapper(interaction: discord.Interaction, *args, **kwargs):  # type: ignore[misc]
            # Vérif guild
            if interaction.guild is None:
                await interaction.response.send_message(
                    message or "Commande uniquement disponible dans une guilde.", ephemeral=ephemeral
                )
                return  # type: ignore[return-value]
            # Récup bitfield permissions
            perms_value = interaction.user.guild_permissions.value  # type: ignore[assignment]
            if (perms_value & bits) != bits:
                # Construction message défaut si non fourni
                default_msg = message or f"Permissions insuffisantes (requis bitmask: {bits})."
                if interaction.response.is_done():
                    await interaction.followup.send(default_msg, ephemeral=ephemeral)
                else:
                    await interaction.response.send_message(default_msg, ephemeral=ephemeral)
                return  # type: ignore[return-value]
            return await func(interaction, *args, **kwargs)
        return wrapper  # type: ignore[return-value]
    return decorator

__all__ = ["require_perms", "ADMINISTRATOR"]
