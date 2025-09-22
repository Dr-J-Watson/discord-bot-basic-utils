"""
Commande slash `/list_users` avec pagination.

Affiche la liste paginée des utilisateurs présents en base de données.
"""
from __future__ import annotations

import discord
import logging
from math import ceil
from db import list_users as list_users_db
from views import list_users as list_users_view

logger = logging.getLogger(__name__)

PAGE_SIZE = 20

def register(bot: discord.Client):
    @bot.tree.command(name="list_users", description="Liste paginée des utilisateurs BD")
    async def list_users_cmd(interaction: discord.Interaction):
        if getattr(bot, "db_pool", None) is None:
            await interaction.response.send_message("DB non configurée", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            total = await list_users_db.count_users(bot.db_pool)  # type: ignore[arg-type]
        except Exception:  # noqa: BLE001
            logger.exception("Erreur count users")
            await interaction.followup.send("Erreur list", ephemeral=True)
            return

        class UsersPaginator(discord.ui.View):
            def __init__(self, *, total: int, author: discord.abc.User):  # type: ignore[override]
                super().__init__(timeout=180)
                self.total = total
                self.author = author
                self.page = 0
                self.pages = max(1, ceil(total / PAGE_SIZE))
                self.message: discord.Message | None = None
                self._refresh_buttons()

            async def fetch_rows(self, page: int):
                offset = page * PAGE_SIZE
                return await list_users_db.fetch_users_page(bot.db_pool, offset, PAGE_SIZE)  # type: ignore[arg-type]

            def _refresh_buttons(self):
                first_btn = self.children[0]
                prev_btn = self.children[1]
                next_btn = self.children[2]
                last_btn = self.children[3]
                first_btn.disabled = prev_btn.disabled = (self.page <= 0)
                next_btn.disabled = last_btn.disabled = (self.page >= self.pages - 1)

            async def build_embed(self):
                rows = await self.fetch_rows(self.page)
                if not rows:
                    return list_users_view.build_empty_embed(self.total)
                return list_users_view.build_users_embed(self.total, self.page, self.pages, PAGE_SIZE, rows)

            async def update_message(self, interaction: discord.Interaction):
                self._refresh_buttons()
                embed = await self.build_embed()
                if self.message is None:
                    self.message = await interaction.followup.send(embed=embed, view=self, ephemeral=True)
                else:
                    await interaction.response.edit_message(embed=embed, view=self)

            async def interaction_check(self, interaction: discord.Interaction) -> bool:  # noqa: D401
                if interaction.user.id != self.author.id:
                    await interaction.response.send_message("Pas pour vous.", ephemeral=True)
                    return False
                return True

            async def on_timeout(self):  # noqa: D401
                for child in self.children:
                    if isinstance(child, discord.ui.Button):
                        child.disabled = True
                if self.message:
                    try:
                        await self.message.edit(view=self)
                    except Exception:  # noqa: BLE001
                        pass

            @discord.ui.button(label="≪", style=discord.ButtonStyle.secondary)
            async def first(self, interaction: discord.Interaction, button: discord.ui.Button):  # type: ignore[override]
                self.page = 0
                await self.update_message(interaction)

            @discord.ui.button(label="‹", style=discord.ButtonStyle.secondary)
            async def prev(self, interaction: discord.Interaction, button: discord.ui.Button):  # type: ignore[override]
                if self.page > 0:
                    self.page -= 1
                await self.update_message(interaction)

            @discord.ui.button(label="›", style=discord.ButtonStyle.secondary)
            async def next(self, interaction: discord.Interaction, button: discord.ui.Button):  # type: ignore[override]
                if self.page < self.pages - 1:
                    self.page += 1
                await self.update_message(interaction)

            @discord.ui.button(label="≫", style=discord.ButtonStyle.secondary)
            async def last(self, interaction: discord.Interaction, button: discord.ui.Button):  # type: ignore[override]
                self.page = self.pages - 1
                await self.update_message(interaction)

            @discord.ui.button(label="Fermer", style=discord.ButtonStyle.danger)
            async def close(self, interaction: discord.Interaction, button: discord.ui.Button):  # type: ignore[override]
                for child in self.children:
                    if isinstance(child, discord.ui.Button):
                        child.disabled = True
                if self.message:
                    await interaction.response.edit_message(content="Fermé", embed=None, view=None)
                else:
                    await interaction.response.send_message("Fermé", ephemeral=True)
                self.stop()

        paginator = UsersPaginator(total=total, author=interaction.user)
        try:
            await paginator.update_message(interaction)
        except Exception:  # noqa: BLE001
            logger.exception("Erreur list_users")
            await interaction.followup.send("Erreur list", ephemeral=True)

__all__ = ["register"]