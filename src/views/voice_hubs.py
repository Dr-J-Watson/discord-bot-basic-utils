"""
Embeds et vues pour la gestion des voice hubs Discord.
"""
from __future__ import annotations

import re
import discord
from typing import Optional, Iterable, Set

CONTROL_TITLE = "Voice Hub"


def build_control_embed(meta: "RoomMeta", channel: discord.VoiceChannel, creator: Optional[discord.Member]) -> discord.Embed:
    embed = discord.Embed(title=f"Contrôle: {channel.name}", color=discord.Color.blurple())
    creator_name = creator.mention if creator else "?"
    embed.add_field(name="Créateur", value=creator_name, inline=True)
    embed.add_field(name="Mode", value=meta.mode, inline=True)
    wl = ", ".join(f"<@{u}>" for u in list(meta.whitelist)[:8]) or "(vide)"
    bl = ", ".join(f"<@{u}>" for u in list(meta.blacklist)[:8]) or "(vide)"
    embed.add_field(name="Whitelist", value=wl, inline=False)
    embed.add_field(name="Blacklist", value=bl, inline=False)
    embed.set_footer(text=f"Channel ID: {channel.id}")
    return embed


def build_control_view(manager, meta: "RoomMeta") -> discord.ui.View:
    class ControlView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=None)

        # ---- helpers ----
        @staticmethod
        def _parse_user_ids(text: str) -> Set[int]:
            ids: Set[int] = set()
            # Mentions <@123> ou <@!123>
            for m in re.findall(r"<@!?(\d+)>", text):
                try:
                    ids.add(int(m))
                except Exception:
                    pass
            # IDs brutes
            for m in re.findall(r"\b(\d{17,20})\b", text):
                try:
                    ids.add(int(m))
                except Exception:
                    pass
            return ids

        async def _apply_permissions(self, rm, guild: discord.Guild):
            # Applique des overwrites simples: blacklist -> connect=False, whitelist -> connect=True (prioritaire)
            channel = guild.get_channel(rm.channel_id)
            if not isinstance(channel, discord.VoiceChannel):
                return
            # Applique pour chaque utilisateur listé
            async def set_overwrite(user_id: int, allow_connect: Optional[bool]):
                member = guild.get_member(user_id)
                if not isinstance(member, discord.Member):
                    return
                current = channel.overwrites_for(member)
                # On ne touche qu'au flag connect pour éviter les surprises
                current.connect = allow_connect
                try:
                    await channel.set_permissions(member, overwrite=current, reason="Voice hub WL/BL update")
                except Exception:
                    pass

            # Les whitelists prennent le pas (connect True)
            for uid in list(rm.whitelist):
                await set_overwrite(uid, True)
            # Blacklist (connect False), retire des whitelists potentiels
            for uid in list(rm.blacklist):
                await set_overwrite(uid, False)

        async def _refresh_panel(self, rm, guild: discord.Guild):
            # Récupère le message de contrôle pour le mettre à jour
            channel = guild.get_channel(rm.channel_id)
            if not isinstance(channel, discord.VoiceChannel):
                return
            creator_member = guild.get_member(rm.creator_id) if rm.creator_id else None
            embed = build_control_embed(rm, channel, creator_member)
            # Essaye d'éditer via interaction courante si possible sinon via fetch
            text_channel_id = getattr(rm, "text_channel_id", None)
            message_id = getattr(rm, "control_message_id", None)
            if text_channel_id and message_id:
                tcand = guild.get_channel(text_channel_id)
                # 1) Tente d'éditer le message existant si possible
                try:
                    if hasattr(tcand, "fetch_message"):
                        msg = await tcand.fetch_message(message_id)  # type: ignore[attr-defined]
                        await msg.edit(embed=embed, view=build_control_view(manager, rm))
                        return
                except Exception:
                    pass
                # 2) Sinon, republie un nouveau panneau et met à jour les IDs
                try:
                    if hasattr(tcand, "send"):
                        new_msg = await tcand.send(embed=embed, view=build_control_view(manager, rm))  # type: ignore[attr-defined]
                        rm.control_message_id = new_msg.id
                        rm.text_channel_id = tcand.id  # type: ignore[assignment]
                        return
                except Exception:
                    pass

        async def interaction_check(self, interaction: discord.Interaction) -> bool:
            if interaction.user.guild_permissions.administrator:
                return True
            rm = manager.room_meta.get(meta.channel_id)
            if rm and rm.creator_id == interaction.user.id:
                return True
            await interaction.response.send_message("Non autorisé.", ephemeral=True)
            return False

        @discord.ui.button(label="Ouvert", style=discord.ButtonStyle.secondary)
        async def mode_open(self, interaction: discord.Interaction, button: discord.ui.Button):  # type: ignore
            await self._set_mode(interaction, "open")

        @discord.ui.button(label="Fermé", style=discord.ButtonStyle.secondary)
        async def mode_closed(self, interaction: discord.Interaction, button: discord.ui.Button):  # type: ignore
            await self._set_mode(interaction, "closed")

        @discord.ui.button(label="Privé", style=discord.ButtonStyle.secondary)
        async def mode_private(self, interaction: discord.Interaction, button: discord.ui.Button):  # type: ignore
            await self._set_mode(interaction, "private")

        # --- Whitelist / Blacklist management ---
        @discord.ui.button(label="WL +", style=discord.ButtonStyle.success)
        async def wl_add(self, interaction: discord.Interaction, button: discord.ui.Button):  # type: ignore
            await self._open_user_select(interaction, list_type="wl", action="add")

        @discord.ui.button(label="WL -", style=discord.ButtonStyle.secondary)
        async def wl_remove(self, interaction: discord.Interaction, button: discord.ui.Button):  # type: ignore
            await self._open_user_select(interaction, list_type="wl", action="remove")

        @discord.ui.button(label="BL +", style=discord.ButtonStyle.danger)
        async def bl_add(self, interaction: discord.Interaction, button: discord.ui.Button):  # type: ignore
            await self._open_user_select(interaction, list_type="bl", action="add")

        @discord.ui.button(label="BL -", style=discord.ButtonStyle.secondary)
        async def bl_remove(self, interaction: discord.Interaction, button: discord.ui.Button):  # type: ignore
            await self._open_user_select(interaction, list_type="bl", action="remove")

        @discord.ui.button(label="Supprimer", style=discord.ButtonStyle.danger)
        async def delete(self, interaction: discord.Interaction, button: discord.ui.Button):  # type: ignore
            rm = manager.room_meta.get(meta.channel_id)
            channel = interaction.guild.get_channel(rm.channel_id) if (interaction.guild and rm) else None
            if isinstance(channel, discord.VoiceChannel):
                try:
                    await channel.delete(reason="Delete dynamic room via panel")
                    manager.dynamic_rooms.discard(channel.id)
                    manager.room_meta.pop(channel.id, None)
                    await interaction.response.edit_message(content="Salon supprimé", embed=None, view=None)
                except Exception:  # noqa: BLE001
                    await interaction.response.send_message("Erreur suppression", ephemeral=True)
            else:
                await interaction.response.send_message("Canal introuvable", ephemeral=True)

        async def _set_mode(self, interaction: discord.Interaction, new_mode: str):
            rm = manager.room_meta.get(meta.channel_id)
            if not rm:
                await interaction.response.send_message("Meta introuvable", ephemeral=True)
                return
            rm.mode = new_mode
            channel = interaction.guild.get_channel(rm.channel_id) if interaction.guild else None
            creator_member = channel.guild.get_member(rm.creator_id) if isinstance(channel, discord.VoiceChannel) else None
            if isinstance(channel, discord.VoiceChannel) and creator_member:
                new_embed = build_control_embed(rm, channel, creator_member)
                try:
                    await interaction.response.edit_message(embed=new_embed, view=self)
                except Exception:  # noqa: BLE001
                    try:
                        await interaction.followup.send("Mode modifié.", ephemeral=True)
                    except Exception:
                        pass
            else:
                await interaction.response.send_message("Channel introuvable", ephemeral=True)

        async def _open_user_select(self, interaction: discord.Interaction, list_type: str, action: str):
            rm = manager.room_meta.get(meta.channel_id)
            if not rm:
                await interaction.response.send_message("Meta introuvable", ephemeral=True)
                return

            class SelectUsersView(discord.ui.View):
                def __init__(self, *, timeout: Optional[float] = 60):
                    super().__init__(timeout=timeout)
                    self.list_type = list_type
                    self.action = action

                    # ADD = UserSelect (libre). REMOVE = Select limité aux IDs présents dans la liste courante
                    if self.action == "add":
                        select = discord.ui.UserSelect(placeholder="Sélectionnez les utilisateurs", min_values=1, max_values=10)

                        async def on_select(sel_inter: discord.Interaction):  # callback for the user select
                            _rm = manager.room_meta.get(meta.channel_id)
                            if not _rm:
                                await sel_inter.response.send_message("Meta introuvable.", ephemeral=True)
                                return
                            ids = []
                            for u in select.values:
                                try:
                                    ids.append(u.id)
                                except Exception:
                                    pass
                            if not ids:
                                await sel_inter.response.send_message("Aucun utilisateur choisi.", ephemeral=True)
                                return
                            if self.list_type == "wl":
                                _rm.whitelist.update(ids)
                                _rm.blacklist.difference_update(ids)
                            else:
                                _rm.blacklist.update(ids)
                                _rm.whitelist.difference_update(ids)
                            try:
                                if sel_inter.guild:
                                    await ControlView._apply_permissions(self, _rm, sel_inter.guild)  # type: ignore[arg-type]
                                    await ControlView._refresh_panel(self, _rm, sel_inter.guild)
                            except Exception:
                                pass
                            await sel_inter.response.edit_message(content=(
                                "Ajoutés : " + ", ".join(f"<@{i}>" for i in ids[:15])
                            ), view=None)

                        select.callback = on_select  # type: ignore[assignment]
                        self.add_item(select)
                    else:
                        # Remove flow: limiter aux utilisateurs déjà dans la liste WL/BL
                        source_ids = list(rm.whitelist if self.list_type == "wl" else rm.blacklist)
                        if not source_ids:
                            # Pas d'utilisateurs à retirer
                            raise RuntimeError("EMPTY_LIST")
                        options = []
                        for uid in source_ids[:25]:  # Discord Select max 25 options
                            member = interaction.guild.get_member(uid) if interaction.guild else None
                            label = member.display_name if isinstance(member, discord.Member) else f"ID {uid}"
                            desc = f"{member.name}" if isinstance(member, discord.Member) else "Utilisateur inconnu"
                            options.append(discord.SelectOption(label=label, value=str(uid), description=desc))
                        select = discord.ui.Select(
                            placeholder="Choisissez à retirer",
                            min_values=1,
                            max_values=min(10, len(options)),
                            options=options,
                        )

                        async def on_select(sel_inter: discord.Interaction):  # callback for limited select
                            _rm = manager.room_meta.get(meta.channel_id)
                            if not _rm:
                                await sel_inter.response.send_message("Meta introuvable.", ephemeral=True)
                                return
                            try:
                                ids = [int(v) for v in select.values]
                            except Exception:
                                ids = []
                            if not ids:
                                await sel_inter.response.send_message("Aucun utilisateur choisi.", ephemeral=True)
                                return
                            if self.list_type == "wl":
                                _rm.whitelist.difference_update(ids)
                            else:
                                _rm.blacklist.difference_update(ids)
                            try:
                                if sel_inter.guild:
                                    await ControlView._apply_permissions(self, _rm, sel_inter.guild)  # type: ignore[arg-type]
                                    await ControlView._refresh_panel(self, _rm, sel_inter.guild)
                            except Exception:
                                pass
                            await sel_inter.response.edit_message(content=(
                                "Retirés : " + ", ".join(f"<@{i}>" for i in ids[:15])
                            ), view=None)

                        select.callback = on_select  # type: ignore[assignment]
                        self.add_item(select)

            try:
                await interaction.response.send_message(
                    content=("Ajouter" if action == "add" else "Retirer") + (" WL" if list_type == "wl" else " BL"),
                    view=SelectUsersView(),
                    ephemeral=True,
                )
            except RuntimeError as e:
                if str(e) == "EMPTY_LIST":
                    await interaction.response.send_message("La liste est vide.", ephemeral=True)
                else:
                    raise

    return ControlView()

