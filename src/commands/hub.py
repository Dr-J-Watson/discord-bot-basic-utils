"""
Groupe de commandes slash `/hub` (list, create, delete, config).

Permet la gestion des voice hubs (salons vocaux dynamiques) via Discord.
"""
from __future__ import annotations

import discord
from discord import app_commands
import logging
from core.voice_hubs.manager import VoiceHubsManager
from db import voice_hubs as db_voice_hubs
from core.permissions import require_perms, ADMINISTRATOR
from views import hub as hub_view

logger = logging.getLogger(__name__)

hub_group = app_commands.Group(name="hub", description="Gestion des voice hubs")

def get_manager(interaction: discord.Interaction) -> VoiceHubsManager:
    mgr = getattr(interaction.client, "voice_hubs", None)
    if mgr is None:
        raise RuntimeError("Voice hubs manager non initialisé")
    return mgr  # type: ignore

@hub_group.command(name="list", description="Lister les hubs actifs")
@require_perms(ADMINISTRATOR, message="Admin requis (bit 8)")
async def hub_list(interaction: discord.Interaction):
    mgr = get_manager(interaction)
    await interaction.response.defer(ephemeral=True)
    if not mgr.hubs:
        await interaction.followup.send(hub_view.msg_no_hub(), ephemeral=True)
        return
    lines = []
    for cid in mgr.hubs:
        ch = interaction.guild.get_channel(cid) if interaction.guild else None
        lines.append(hub_view.fmt_hub_list_line(cid, ch.name if ch else None))
    await interaction.followup.send("\n".join(lines), ephemeral=True)


def _voice_choices(guild: discord.Guild, mgr: VoiceHubsManager, current: str, include_hubs: bool, include_non_hubs: bool):
    current_lower = (current or '').lower()
    choices: list[app_commands.Choice[str]] = []
    for ch in guild.channels:
        if not isinstance(ch, discord.VoiceChannel):
            continue
        is_hub = ch.id in mgr.hubs
        if is_hub and not include_hubs:
            continue
        if (not is_hub) and not include_non_hubs:
            continue
        if current_lower and current_lower not in ch.name.lower():
            continue
        choices.append(app_commands.Choice(name=ch.name[:100], value=str(ch.id)))
        if len(choices) >= 25:
            break
    return choices


@hub_group.command(name="create", description="Transformer un salon vocal en hub")
@app_commands.describe(channel="Salon vocal à convertir en hub")
@require_perms(ADMINISTRATOR, message="Admin requis (bit 8)")
async def hub_create(interaction: discord.Interaction, channel: str):
    mgr = get_manager(interaction)
    await interaction.response.defer(ephemeral=True)
    ch = interaction.guild.get_channel(int(channel)) if interaction.guild else None
    if not isinstance(ch, discord.VoiceChannel):
        await interaction.followup.send(hub_view.msg_channel_invalide(), ephemeral=True)
        return
    if ch.id in mgr.hubs:
        await interaction.followup.send(hub_view.msg_deja_hub(), ephemeral=True)
        return
    await mgr.add_hub(ch)
    await interaction.followup.send(hub_view.msg_hub_ajoute(ch.name, ch.id), ephemeral=True)


@hub_group.command(name="delete", description="Désactiver un hub")
@app_commands.describe(channel="Hub à désactiver")
@require_perms(ADMINISTRATOR, message="Admin requis (bit 8)")
async def hub_delete(interaction: discord.Interaction, channel: str):
    mgr = get_manager(interaction)
    await interaction.response.defer(ephemeral=True)
    ch = interaction.guild.get_channel(int(channel)) if interaction.guild else None
    if not isinstance(ch, discord.VoiceChannel) or ch.id not in mgr.hubs:
        await interaction.followup.send(hub_view.msg_pas_un_hub(), ephemeral=True)
        return
    await mgr.remove_hub(ch.id)
    await interaction.followup.send(hub_view.msg_hub_desactive(ch.name), ephemeral=True)


@hub_group.command(name="config", description="Configurer naming pattern & user limit d'un hub")
@app_commands.describe(
    channel="Hub à configurer",
    pattern="Pattern de nom (placeholders: {user} {display} {n})",
    limit="Limite utilisateurs (0 = hérite du hub)",
)
@require_perms(ADMINISTRATOR, message="Admin requis (bit 8)")
async def hub_config(
    interaction: discord.Interaction,
    channel: str,
    pattern: str | None = None,
    limit: int | None = None,
):
    mgr = get_manager(interaction)
    await interaction.response.defer(ephemeral=True)
    ch = interaction.guild.get_channel(int(channel)) if interaction.guild else None
    if not isinstance(ch, discord.VoiceChannel) or ch.id not in mgr.hubs:
        await interaction.followup.send("Pas un hub.", ephemeral=True)
        return
    if pattern and len(pattern) > 100:
        await interaction.followup.send(hub_view.msg_pattern_trop_long(), ephemeral=True)
        return
    if pattern:
        test_pattern = pattern.replace("{user}", "u").replace("{display}", "d").replace("{n}", "1")
        if "{" in test_pattern or "}" in test_pattern:
            await interaction.followup.send(hub_view.msg_pattern_placeholders(), ephemeral=True)
            return
    max_rooms = None
    if limit is not None:
        if limit < 0 or limit > 99:
            await interaction.followup.send(hub_view.msg_limite_invalide(), ephemeral=True)
            return
        # Ici limit représente le plafond de rooms dynamiques (max_rooms)
        max_rooms = limit if limit > 0 else None
    await db_voice_hubs.update_hub_config(mgr.pool, ch.id, pattern, max_rooms)
    msg_parts = ["Config mise à jour"]
    if pattern:
        msg_parts.append(f"pattern='{pattern}'")
    if limit is not None:
        msg_parts.append(f"max_rooms={'illimité' if limit==0 else limit}")
    await interaction.followup.send(hub_view.msg_config_update(msg_parts), ephemeral=True)


@hub_create.autocomplete('channel')
async def hub_create_channel_ac(interaction: discord.Interaction, current: str):
    try:
        mgr = get_manager(interaction)
    except Exception:  # noqa: BLE001
        return []
    if not interaction.guild:
        return []
    return _voice_choices(interaction.guild, mgr, current, include_hubs=False, include_non_hubs=True)


@hub_delete.autocomplete('channel')
async def hub_delete_channel_ac(interaction: discord.Interaction, current: str):
    try:
        mgr = get_manager(interaction)
    except Exception:  # noqa: BLE001
        return []
    if not interaction.guild:
        return []
    return _voice_choices(interaction.guild, mgr, current, include_hubs=True, include_non_hubs=False)


@hub_config.autocomplete('channel')
async def hub_config_channel_ac(interaction: discord.Interaction, current: str):
    try:
        mgr = get_manager(interaction)
    except Exception:  # noqa: BLE001
        return []
    if not interaction.guild:
        return []
    return _voice_choices(interaction.guild, mgr, current, include_hubs=True, include_non_hubs=False)


def register(bot: discord.Client):
    bot.tree.add_command(hub_group)

__all__ = ["register"]