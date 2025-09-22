"""
Handlers pour les événements membres Discord (join, update, username).

Chaque handler persiste immédiatement les données en base (upsert) si un pool est disponible.
En cas d'erreur, le workflow Discord n'est pas bloqué (log + ignore).
"""
from __future__ import annotations

import logging
import discord

from core import db
from db import welcome as welcome_db
from views.welcome import build_welcome_embed

logger = logging.getLogger(__name__)


def setup(bot: discord.Client):
    @bot.event
    async def on_member_join(member: discord.Member):
        pool = getattr(bot, "db_pool", None)
        if pool is None:
            return
        try:
            await db.upsert_user(pool, member.id, member.display_name, member.name)
            logger.info("Join -> upsert %s (%s)", member.display_name, member.id)
        except Exception:
            logger.exception("Echec upsert join")
        # Envoi message de bienvenue si configuré
        try:
            cid = await welcome_db.get_welcome_channel(pool, member.guild.id)
            if cid:
                ch = member.guild.get_channel(cid)
                if isinstance(ch, (discord.TextChannel, discord.Thread)):
                    embed = await build_welcome_embed(member)
                    await ch.send(embed=embed)
        except Exception:
            logger.exception("Echec envoi message de bienvenue")

    @bot.event
    async def on_member_update(before: discord.Member, after: discord.Member):
        pool = getattr(bot, "db_pool", None)
        if pool is None:
            return
        if before.display_name != after.display_name:
            try:
                await db.upsert_user(pool, after.id, after.display_name, after.name)
                logger.info("Display change: %s -> %s (%s)", before.display_name, after.display_name, after.id)
            except Exception:
                logger.exception("Echec maj display_name")

    @bot.event
    async def on_user_update(before: discord.User, after: discord.User):
        pool = getattr(bot, "db_pool", None)
        if pool is None:
            return
        if before.name != after.name:
            try:
                await db.upsert_user(pool, after.id, getattr(after, 'display_name', after.name), after.name)
                logger.info("Username change: %s -> %s (%s)", before.name, after.name, after.id)
            except Exception:
                logger.exception("Echec maj username")

