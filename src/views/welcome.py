"""
Embed de bienvenue stylisé Valorant (propre et minimal).
"""
from __future__ import annotations
from typing import Optional
import discord

VALORANT_RED = discord.Color.from_str("#FF4655")  # Rouge Valorant

async def build_welcome_embed(
    member: discord.Member,
    *,
    line: Optional[str] = None,
    color: Optional[discord.Color] = None,
    banner_url: Optional[str] = None,  # optionnel : image de bannière
) -> discord.Embed:
    guild = member.guild

    title = f"‹ BIENVENUE, AGENT {member.display_name} ›"
    desc = line or f"Accès accordé : {member.mention} a rejoint {guild.name}. Protocole actif."

    e = discord.Embed(
        title=title,
        description=f"╺━━━━━━━━━━━━━━━━╸\n{desc}\n╺━━━━━━━━━━━━━━━━╸",
        color=color or VALORANT_RED,
        timestamp=discord.utils.utcnow(),
    )

    # En-tête avec icône du serveur si dispo
    if guild.icon:
        e.set_author(name="PROTOCOL // VALORANT", icon_url=guild.icon.url)

    # Avatar du membre
    e.set_thumbnail(url=member.display_avatar.url)

    # Bannière optionnelle (ou bannière du serveur si disponible)
    if banner_url:
        e.set_image(url=banner_url)
    elif getattr(guild, "banner", None):
        e.set_image(url=guild.banner.url)

    e.set_footer(text="Respect • Jeu d’équipe • Fair-play")
    return e
