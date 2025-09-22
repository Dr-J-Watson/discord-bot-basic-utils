"""
Commande slash `/sync_users`.

Synchronise les membres du serveur Discord dans la base de données.
Accessible uniquement aux administrateurs.
"""
from __future__ import annotations

import discord
import logging
from core.permissions import require_perms, ADMINISTRATOR
from views import sync_users as sync_view
from db import sync_users as sync_db

logger = logging.getLogger(__name__)

def register(bot: discord.Client):
    @bot.tree.command(name="sync_users", description="Synchronise les membres dans la base (admin)")
    @require_perms(ADMINISTRATOR, message="Admin requis (bit 8).")
    async def sync_users_cmd(interaction: discord.Interaction):
        if getattr(bot, "db_pool", None) is None:
            await interaction.response.send_message(sync_view.build_no_db(), ephemeral=True)
            return
        await interaction.response.defer(thinking=True, ephemeral=True)
        guild = interaction.guild
        if guild is None:
            await interaction.followup.send("Guild introuvable", ephemeral=True)
            return
        try:
            members = guild.members
            if not members:
                members = await guild.fetch_members(limit=None).flatten()
        except Exception:  # noqa: BLE001
            members = guild.members
        rows = ((m.id, m.display_name, m.name) for m in members if not m.bot)
        try:
            count = await sync_db.bulk_upsert_users(bot.db_pool, rows)  # type: ignore[arg-type]
            await interaction.followup.send(sync_view.build_success(count), ephemeral=True)
        except Exception:  # noqa: BLE001
            logger.exception("Erreur sync users")
            await interaction.followup.send(sync_view.build_error(), ephemeral=True)

__all__ = ["register"]