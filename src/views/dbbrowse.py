"""
Embeds et vues pour la commande `/dbbrowse`.
"""
from __future__ import annotations
import discord
from db.dbbrowse import TablePage

PRIMARY_COLOR = 0x2b6cb0

def build_root_embed(tables: list[str]) -> discord.Embed:
    e = discord.Embed(title="Navigation base de données", description="Sélectionnez une table.", color=PRIMARY_COLOR)
    e.add_field(name="Tables", value=", ".join(tables) or "(aucune)", inline=False)
    return e

def build_table_embed(page: TablePage) -> discord.Embed:
    title = f"Table: {page.table} (page {page.page+1})"
    e = discord.Embed(title=title, color=PRIMARY_COLOR)
    if page.total == 0:
        e.description = "Aucune ligne."
        return e
    header = " | ".join(page.columns)
    lines = [f"`{header}`"]
    for row in page.rows:
        cells = []
        for v in row:
            txt = str(v)
            if len(txt) > 24:
                txt = txt[:21] + '…'
            cells.append(txt.replace('`',''))
        lines.append(" | ".join(cells))
    preview = "\n".join(lines)
    if len(preview) > 3800:
        preview = preview[:3800] + "\n…"
    e.description = f"Total lignes: {page.total}\n``{preview}``"
    return e

__all__ = ["build_root_embed", "build_table_embed"]
