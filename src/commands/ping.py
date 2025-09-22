"""
Commande slash `/ping`.

Affiche la latence du bot en millisecondes.
Accessible uniquement aux administrateurs.
"""
from __future__ import annotations

import discord
from core.permissions import require_perms, ADMINISTRATOR

def register(bot: discord.Client):
    @bot.tree.command(name="ping", description="Latence du bot")
    @require_perms(ADMINISTRATOR, message="Ping réservé aux administrateurs (bit 8).")
    async def ping(interaction: discord.Interaction):  # noqa: D401
        await interaction.response.send_message(f"Pong {bot.latency*1000:.0f} ms", ephemeral=True)

__all__ = ["register"]