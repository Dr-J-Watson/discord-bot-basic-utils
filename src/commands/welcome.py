"""
Commandes slash pour gérer le salon de bienvenue Discord.

Commandes disponibles :
- /welcome set <salon> : définit le salon pour les messages de bienvenue
- /welcome show : affiche le salon configuré
- /welcome clear : désactive les messages de bienvenue
- /welcome send <membre> : envoie un embed de bienvenue pour un membre
"""
from __future__ import annotations

import logging
import discord
from discord import app_commands

from core.permissions import require_perms, ADMINISTRATOR
from db import welcome as db
from views.welcome import build_welcome_embed

logger = logging.getLogger(__name__)

welcome = app_commands.Group(name="welcome", description="Configuration du salon de bienvenue")


@welcome.command(name="set", description="Définir le salon de bienvenue")
@app_commands.describe(salon="Salon où envoyer le message de bienvenue")
@require_perms(ADMINISTRATOR, message="Admin requis")
async def set_cmd(inter: discord.Interaction, salon: discord.TextChannel):
    if not inter.guild:
        await inter.response.send_message("A exécuter dans une guilde.", ephemeral=True)
        return
    pool = getattr(inter.client, 'db_pool', None)
    if pool is None:
        await inter.response.send_message("DB non configurée.", ephemeral=True)
        return
    await db.set_welcome_channel(pool, inter.guild.id, salon.id)
    await inter.response.send_message(f"Salon de bienvenue défini sur {salon.mention}.", ephemeral=True)


@welcome.command(name="show", description="Afficher le salon de bienvenue")
@require_perms(ADMINISTRATOR)
async def show_cmd(inter: discord.Interaction):
    if not inter.guild:
        await inter.response.send_message("A exécuter dans une guilde.", ephemeral=True)
        return
    pool = getattr(inter.client, 'db_pool', None)
    if pool is None:
        await inter.response.send_message("DB non configurée.", ephemeral=True)
        return
    cid = await db.get_welcome_channel(pool, inter.guild.id)
    if cid:
        ch = inter.guild.get_channel(cid)
        await inter.response.send_message(f"Salon de bienvenue: {ch.mention if ch else f'<#{cid}>'}", ephemeral=True)
    else:
        await inter.response.send_message("Aucun salon de bienvenue configuré.", ephemeral=True)


@welcome.command(name="clear", description="Désactiver le message de bienvenue")
@require_perms(ADMINISTRATOR)
async def clear_cmd(inter: discord.Interaction):
    if not inter.guild:
        await inter.response.send_message("A exécuter dans une guilde.", ephemeral=True)
        return
    pool = getattr(inter.client, 'db_pool', None)
    if pool is None:
        await inter.response.send_message("DB non configurée.", ephemeral=True)
        return
    await db.clear_welcome_channel(pool, inter.guild.id)
    await inter.response.send_message("Message de bienvenue désactivé.", ephemeral=True)


def register(bot: discord.Client):
    try:
        bot.tree.add_command(welcome)
    except Exception:
        logger.exception("Echec enregistrement commandes welcome")


@welcome.command(name="send", description="Envoyer un message de bienvenue pour un membre")
@app_commands.describe(membre="Membre à accueillir (mention @)")
@require_perms(ADMINISTRATOR)
async def send_cmd(inter: discord.Interaction, membre: discord.Member):
    if not inter.guild:
        await inter.response.send_message("A exécuter dans une guilde.", ephemeral=True)
        return
    pool = getattr(inter.client, 'db_pool', None)
    if pool is None:
        await inter.response.send_message("DB non configurée.", ephemeral=True)
        return

    # Déférer pour éviter le timeout si récupération externe/embeds prend du temps
    await inter.response.defer(ephemeral=True)

    cid = await db.get_welcome_channel(pool, inter.guild.id)
    channel = inter.guild.get_channel(cid) if cid else None
    if not isinstance(channel, discord.TextChannel):
        if isinstance(inter.channel, discord.TextChannel):
            channel = inter.channel
        else:
            await inter.followup.send(
                "Aucun salon de bienvenue valide (configuré ou courant). Utilisez /welcome set.",
                ephemeral=True,
            )
            return

    try:
        embed = await build_welcome_embed(membre)
        await channel.send(embed=embed)
        await inter.followup.send(
            f"Message de bienvenue envoyé dans {channel.mention} pour {membre.mention}.",
            ephemeral=True,
        )
    except discord.Forbidden:
        # Essaye dernier recours: envoyer dans le salon de la commande si différent
        if isinstance(inter.channel, discord.TextChannel) and inter.channel.id != getattr(channel, 'id', 0):
            try:
                embed = await build_welcome_embed(membre)
                await inter.channel.send(embed=embed)
                await inter.followup.send(
                    f"Permissions insuffisantes dans {getattr(channel, 'mention', '#?')}, envoyé ici à la place.",
                    ephemeral=True,
                )
                return
            except Exception:
                pass
        await inter.followup.send(
            "Permissions insuffisantes pour envoyer un message dans le salon configuré.",
            ephemeral=True,
        )
    except Exception:
        logger.exception("Echec envoi welcome manuel")
        await inter.followup.send("Echec d'envoi du message de bienvenue.", ephemeral=True)
