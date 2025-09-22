"""
Commande slash `/dbbrowse` refactorisée.

Utilise les modules db/ et views/ pour la logique métier et l'UI.
Permet de parcourir les tables de la base de données via Discord.
"""
from __future__ import annotations

import discord
from discord import app_commands
import logging
from dataclasses import dataclass, field
from typing import Dict, Optional
from db import dbbrowse as db_layer
from views import dbbrowse as view_layer

logger = logging.getLogger(__name__)

@dataclass
class BrowserSession:
    user_id: int
    tables: list[str]
    current_table: Optional[str] = None
    page_cache: Dict[tuple[str, int], db_layer.TablePage] = field(default_factory=dict)
    current_page_index: int = 0
    page_size: int = 10


class DBBrowserView(discord.ui.View):
    def __init__(self, pool, session: BrowserSession, timeout: int = 300):
        super().__init__(timeout=timeout)
        self.pool = pool
        self.session = session
        self.message: Optional[discord.Message] = None

    async def on_timeout(self):  # noqa: D401
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except Exception:  # noqa: BLE001
                pass

    async def get_page(self, table: str, page: int):
        # Validation défensive: table doit exister dans la liste blanche connue
        if table not in self.session.tables:
            raise ValueError("Table non autorisée")
        key = (table, page)
        if key not in self.session.page_cache:
            self.session.page_cache[key] = await db_layer.fetch_page(self.pool, table, page, self.session.page_size)
        return self.session.page_cache[key]

    def build_current_embed(self):
        if not self.session.current_table:
            return view_layer.build_root_embed(self.session.tables)
        page_obj = self.session.page_cache.get((self.session.current_table, self.session.current_page_index))
        if not page_obj:
            # Fallback embed minimal (ne devrait pas arriver car get_page est appelé avant)
            return view_layer.build_root_embed(self.session.tables)
        return view_layer.build_table_embed(page_obj)

    async def refresh_table(self, interaction: discord.Interaction):
        if not self.session.current_table:
            await interaction.response.edit_message(embed=view_layer.build_root_embed(self.session.tables), view=self)
            return
        # Recharger page courante (invalider cache entrée)
        key = (self.session.current_table, self.session.current_page_index)
        try:
            self.session.page_cache[key] = await db_layer.fetch_page(
                self.pool, self.session.current_table, self.session.current_page_index, self.session.page_size
            )
        except Exception:  # noqa: BLE001
            pass
        await interaction.response.edit_message(embed=self.build_current_embed(), view=self)

class TableSelect(discord.ui.Select):
    def __init__(self, browser_view: DBBrowserView):
        self.browser_view = browser_view
        options = [discord.SelectOption(label=t, value=t) for t in browser_view.session.tables[:25]]
        super().__init__(placeholder="Choisir une table", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):  # type: ignore
        if interaction.user.id != self.browser_view.session.user_id:
            await interaction.response.defer(ephemeral=True)
            return
        table = self.values[0]
        self.browser_view.session.current_table = table
        self.browser_view.session.current_page_index = 0
        await self.browser_view.get_page(table, 0)
        await interaction.response.edit_message(embed=self.browser_view.build_current_embed(), view=self.browser_view)


class NavButtons(discord.ui.View):
    def __init__(self, browser: DBBrowserView):
        super().__init__(timeout=None)
        self.browser = browser

    async def _move(self, interaction: discord.Interaction, direction: str):
        if interaction.user.id != self.browser.session.user_id:
            await interaction.response.defer(ephemeral=True)
            return
        if not self.browser.session.current_table:
            await interaction.response.defer()
            return
        current = self.browser.session.current_page_index
        new_page = current
        if direction == 'first':
            new_page = 0
        elif direction == 'prev':
            new_page = max(current - 1, 0)
        elif direction == 'next':
            new_page = current + 1
        elif direction == 'last':  # best effort: increment until empty
            # naive: chercher jusqu'à page vide (limité à 100 pages)
            test_page = current
            while test_page - current < 100:
                page_obj = await db_layer.fetch_page(
                    self.browser.pool, self.browser.session.current_table, test_page, self.browser.session.page_size
                )
                self.browser.session.page_cache[(self.browser.session.current_table, test_page)] = page_obj
                if page_obj.total <= test_page * page_obj.page_size:
                    break
                test_page += 1
            new_page = test_page
        if new_page == current:
            await interaction.response.defer()
            return
        self.browser.session.current_page_index = new_page
        await self.browser.get_page(self.browser.session.current_table, new_page)
        await interaction.response.edit_message(embed=self.browser.build_current_embed(), view=self.browser)

    @discord.ui.button(label="Retour", style=discord.ButtonStyle.danger)
    async def back_tables(self, interaction: discord.Interaction, button: discord.ui.Button):  # type: ignore
        if interaction.user.id != self.browser.session.user_id:
            await interaction.response.defer(ephemeral=True)
            return
        self.browser.session.current_table = None
        await interaction.response.edit_message(embed=view_layer.build_root_embed(self.browser.session.tables), view=self.browser)

    @discord.ui.button(label="<<", style=discord.ButtonStyle.secondary)
    async def first_page(self, interaction: discord.Interaction, button: discord.ui.Button):  # type: ignore
        await self._move(interaction, 'first')

    @discord.ui.button(label="<", style=discord.ButtonStyle.secondary)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):  # type: ignore
        await self._move(interaction, 'prev')

    @discord.ui.button(label=">", style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):  # type: ignore
        await self._move(interaction, 'next')

    @discord.ui.button(label=">>", style=discord.ButtonStyle.secondary)
    async def last_page(self, interaction: discord.Interaction, button: discord.ui.Button):  # type: ignore
        await self._move(interaction, 'last')

    @discord.ui.button(label="Refresh", style=discord.ButtonStyle.primary)
    async def refresh_btn(self, interaction: discord.Interaction, button: discord.ui.Button):  # type: ignore
        await self.browser.refresh_table(interaction)


def is_guild_owner(inter: discord.Interaction) -> bool:
    return inter.guild is not None and inter.user.id == inter.guild.owner_id


def owner_only():
    def predicate(inter: discord.Interaction):
        if not is_guild_owner(inter):
            raise app_commands.CheckFailure("Réservé au propriétaire du serveur.")
        return True
    return app_commands.check(predicate)


def register(bot: discord.Client):
    @app_commands.command(name="dbbrowse", description="(Owner) Parcourir la base en lecture seule")
    @owner_only()
    async def db_browse(interaction: discord.Interaction):
        pool = getattr(interaction.client, 'db_pool', None)
        if pool is None:
            await interaction.response.send_message("Pool DB indisponible", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            tables = await db_layer.fetch_tables(pool)
        except Exception:  # noqa: BLE001
            await interaction.followup.send("Erreur récupération tables", ephemeral=True)
            return
        session = BrowserSession(user_id=interaction.user.id, tables=tables)
        browser_view = DBBrowserView(pool, session)
        # Add select
        browser_view.add_item(TableSelect(browser_view))
        # Add buttons
        for child in NavButtons(browser_view).children:
            browser_view.add_item(child)
        embed = view_layer.build_root_embed(tables)
        msg = await interaction.followup.send(embed=embed, view=browser_view, ephemeral=True)
        browser_view.message = msg

    @db_browse.error
    async def db_browse_error(interaction: discord.Interaction, error: app_commands.AppCommandError):  # type: ignore
        if isinstance(error, app_commands.CheckFailure):
            try:
                if not interaction.response.is_done():
                    await interaction.response.send_message("Commande réservée au propriétaire du serveur.", ephemeral=True)
                else:
                    await interaction.followup.send("Commande réservée au propriétaire du serveur.", ephemeral=True)
            except Exception:  # noqa: BLE001
                pass
            logger.debug("dbbrowse refusé pour user %s (owner only)", interaction.user.id)
            return
        raise error

    bot.tree.add_command(db_browse)

__all__ = ["register"]