"""
Embeds pour la commande `/list_users`.
"""
from __future__ import annotations
import discord

def build_empty_embed(total: int) -> discord.Embed:
    e = discord.Embed(title=f"Utilisateurs ({total})", description="Aucun utilisateur en base.", color=discord.Color.blurple())
    return e

def build_users_embed(total: int, page: int, pages: int, page_size: int, rows):
    e = discord.Embed(title=f"Utilisateurs ({total})", color=discord.Color.blurple())
    lines = []
    start_index = page * page_size
    for idx, r in enumerate(rows, start=start_index + 1):
        lines.append(f"**{idx}.** `{r['id']}` — {r['display_name']} (@{r['username']})")
    e.description = "\n".join(lines)
    e.set_footer(text=f"Page {page + 1}/{pages} • {page_size} par page")
    return e

__all__ = ["build_empty_embed", "build_users_embed"]