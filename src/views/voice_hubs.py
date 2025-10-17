"""
Embeds et vues pour la gestion des voice hubs Discord.
"""
from __future__ import annotations

import re
import discord
from typing import Optional, Set

CONTROL_TITLE = "Voice Hub"


def build_control_embed(meta: "RoomMeta", channel: discord.VoiceChannel, creator: Optional[discord.Member]) -> discord.Embed:
    embed = discord.Embed(title=f"Contrôle: {channel.name}", color=discord.Color.blurple())
    creator_name = creator.mention if creator else "?"
    embed.add_field(name="Créateur", value=creator_name, inline=True)
    mode_labels = {
        "open": "Ouvert",
        "closed": "Fermé",
        "private": "Privé",
        "conference": "Conférence",
    }
    embed.add_field(name="Mode", value=mode_labels.get(meta.mode, meta.mode), inline=True)
    wl = ", ".join(f"<@{u}>" for u in list(meta.whitelist)[:8]) or "(vide)"
    bl = ", ".join(f"<@{u}>" for u in list(meta.blacklist)[:8]) or "(vide)"
    embed.add_field(name="Whitelist", value=wl, inline=False)
    embed.add_field(name="Blacklist", value=bl, inline=False)
    if meta.mode == "conference":
        allowed_preview = ", ".join(f"<@{u}>" for u in list(meta.conference_allowed)[:8]) or "(aucun)"
        embed.add_field(name="Conférence", value=allowed_preview, inline=False)
    embed.set_footer(text=f"Channel ID: {channel.id}")
    return embed


def build_control_view(manager, meta: "RoomMeta", *, readonly: bool = False) -> discord.ui.View:
    class ControlView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=None)
            self.readonly = readonly
            if self.readonly:
                for child in self.children:
                    child.disabled = True

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

        async def _apply_permissions(self, rm, guild: Optional[discord.Guild] = None):
            if guild is None:
                _, guild = self._resolve_channel_and_guild(rm)
            if not isinstance(guild, discord.Guild):
                return
            try:
                await manager.apply_room_permissions(rm, guild)
            except Exception:
                pass

        async def _refresh_panel(self, rm, guild: Optional[discord.Guild] = None):
            # Récupère le message de contrôle pour le mettre à jour
            channel, resolved_guild = self._resolve_channel_and_guild(rm)
            if isinstance(resolved_guild, discord.Guild):
                guild = resolved_guild
            if not isinstance(channel, discord.VoiceChannel) or not isinstance(guild, discord.Guild):
                return
            creator_member = guild.get_member(rm.creator_id) if rm.creator_id else None
            embed = build_control_embed(rm, channel, creator_member)
            # Essaye d'éditer via interaction courante si possible sinon via fetch
            text_channel_id = getattr(rm, "text_channel_id", None)
            message_id = getattr(rm, "control_message_id", None)
            if text_channel_id and message_id:
                tcand = manager.bot.get_channel(text_channel_id)
                if tcand is None and isinstance(guild, discord.Guild):
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
                        rm.control_is_dm = isinstance(tcand, discord.DMChannel)
                        return
                except Exception:
                    pass

        @staticmethod
        def _resolve_channel_and_guild(rm):
            channel = manager.bot.get_channel(rm.channel_id)
            guild = channel.guild if isinstance(channel, discord.VoiceChannel) else None
            return channel, guild

        async def interaction_check(self, interaction: discord.Interaction) -> bool:
            if self.readonly:
                await interaction.response.send_message("Panneau en lecture seule.", ephemeral=True)
                return False
            rm = manager.room_meta.get(meta.channel_id)
            if not rm:
                await interaction.response.send_message("Meta introuvable", ephemeral=True)
                return False
            channel, guild = self._resolve_channel_and_guild(rm)
            if isinstance(guild, discord.Guild):
                member = guild.get_member(interaction.user.id)
                if member and member.guild_permissions.administrator:
                    return True
            if rm.creator_id == interaction.user.id:
                return True
            await interaction.response.send_message("Non autorisé.", ephemeral=True)
            return False

        @discord.ui.button(label="Ouvert", style=discord.ButtonStyle.secondary, row=0)
        async def mode_open(self, interaction: discord.Interaction, button: discord.ui.Button):  # type: ignore
            await self._set_mode(interaction, "open")

        @discord.ui.button(label="Fermé", style=discord.ButtonStyle.secondary, row=0)
        async def mode_closed(self, interaction: discord.Interaction, button: discord.ui.Button):  # type: ignore
            await self._set_mode(interaction, "closed")

        @discord.ui.button(label="Privé", style=discord.ButtonStyle.secondary, row=0)
        async def mode_private(self, interaction: discord.Interaction, button: discord.ui.Button):  # type: ignore
            await self._set_mode(interaction, "private")

        @discord.ui.button(label="Conférence", style=discord.ButtonStyle.secondary, row=0)
        async def mode_conference(self, interaction: discord.Interaction, button: discord.ui.Button):  # type: ignore
            await self._set_mode(interaction, "conference")

        # --- Whitelist / Blacklist management ---
        @discord.ui.button(label="WL +", style=discord.ButtonStyle.success, row=1)
        async def wl_add(self, interaction: discord.Interaction, button: discord.ui.Button):  # type: ignore
            await self._open_user_select(interaction, list_type="wl", action="add")

        @discord.ui.button(label="WL -", style=discord.ButtonStyle.secondary, row=1)
        async def wl_remove(self, interaction: discord.Interaction, button: discord.ui.Button):  # type: ignore
            await self._open_user_select(interaction, list_type="wl", action="remove")

        @discord.ui.button(label="BL +", style=discord.ButtonStyle.danger, row=1)
        async def bl_add(self, interaction: discord.Interaction, button: discord.ui.Button):  # type: ignore
            await self._open_user_select(interaction, list_type="bl", action="add")

        @discord.ui.button(label="BL -", style=discord.ButtonStyle.secondary, row=1)
        async def bl_remove(self, interaction: discord.Interaction, button: discord.ui.Button):  # type: ignore
            await self._open_user_select(interaction, list_type="bl", action="remove")

        @discord.ui.button(label="Purger", style=discord.ButtonStyle.danger, row=2)
        async def purge(self, interaction: discord.Interaction, button: discord.ui.Button):  # type: ignore
            rm = manager.room_meta.get(meta.channel_id)
            if not rm:
                await interaction.response.send_message("Canal ou métadonnées introuvables", ephemeral=True)
                return
            channel, guild = self._resolve_channel_and_guild(rm)
            if not isinstance(channel, discord.VoiceChannel) or not isinstance(guild, discord.Guild):
                await interaction.response.send_message("Canal ou métadonnées introuvables", ephemeral=True)
                return
            try:
                await self._apply_permissions(rm, guild)
            except Exception:
                pass

            disconnected_users = []
            try:
                allowed_ids = {rm.creator_id} | set(rm.whitelist)
                if rm.mode == "conference":
                    allowed_ids.update(rm.conference_allowed)

                # Appliquer les règles selon le mode du salon
                for member in channel.members:
                    should_disconnect = False
                    
                    # Toujours déconnecter les utilisateurs en blacklist
                    if member.id in rm.blacklist:
                        should_disconnect = True
                    
                    # Modes privés/fermés/conférence -> restreindre aux autorisés
                    elif rm.mode in {"private", "closed", "conference"} and member.id not in allowed_ids:
                        should_disconnect = True
                    
                    # En mode fermé, déconnecter ceux en blacklist seulement
                    # (en mode ouvert, seule la blacklist compte)
                    
                    if should_disconnect:
                        try:
                            await member.move_to(None, reason="Purge - règles du salon appliquées")
                            disconnected_users.append(member.display_name)
                        except Exception:  # noqa: BLE001
                            pass
                
                # Message de résultat
                if disconnected_users:
                    message = f"Purge effectuée. {len(disconnected_users)} utilisateur(s) déconnecté(s): {', '.join(disconnected_users[:10])}"
                    if len(disconnected_users) > 10:
                        message += f" et {len(disconnected_users) - 10} autre(s)"
                else:
                    message = "Purge effectuée. Aucun utilisateur à déconnecter."
                    
                await interaction.response.send_message(message, ephemeral=True)
                
            except Exception:  # noqa: BLE001
                await interaction.response.send_message("Erreur lors de la purge", ephemeral=True)

        @discord.ui.button(label="Transférer", style=discord.ButtonStyle.primary, row=2)
        async def transfer(self, interaction: discord.Interaction, button: discord.ui.Button):  # type: ignore
            rm = manager.room_meta.get(meta.channel_id)
            if not rm:
                await interaction.response.send_message("Meta introuvable", ephemeral=True)
                return
            await self._open_transfer_dialog(interaction, rm)

        @discord.ui.button(label="Supprimer", style=discord.ButtonStyle.danger, row=2)
        async def delete(self, interaction: discord.Interaction, button: discord.ui.Button):  # type: ignore
            rm = manager.room_meta.get(meta.channel_id)
            if not rm:
                await interaction.response.send_message("Canal introuvable", ephemeral=True)
                return
            channel, _ = self._resolve_channel_and_guild(rm)
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
        
        
        @discord.ui.button(label="Help", style=discord.ButtonStyle.secondary, row=3)
        async def show_help(self, interaction: discord.Interaction, button: discord.ui.Button):  # type: ignore
            rm = manager.room_meta.get(meta.channel_id)
            if not rm:
                await interaction.response.send_message("Meta introuvable", ephemeral=True)
                return
            help_embed = discord.Embed(
                title="Panneau Voice Hub — Aide",
                color=discord.Color.blurple(),
                description="Guide rapide de chaque bouton. Les règles de purge changent selon le mode actif.",
            )
            help_embed.add_field(
                name="Modes",
                value=(
                    "**Ouvert** — Tout le monde peut entrer ; purge exclut seulement la blacklist.\n"
                    "**Fermé** — Accès limité au créateur et à la whitelist ; purge renvoie les autres.\n"
                    "**Privé** — Salon masqué et verrouillé hors whitelist ; purge expulse les visiteurs non autorisés.\n"
                    "**Conférence** — Fige les présents ; purge chasse ceux hors liste conférence/whitelist."
                ),
                inline=False,
            )
            help_embed.add_field(
                name="Gestion des accès",
                value=(
                    "**WL + / WL -** — Ajoute ou retire de la whitelist, donne la priorité d'accès.\n"
                    "**BL + / BL -** — Ajoute ou retire de la blacklist, bloque complètement."
                ),
                inline=False,
            )
            help_embed.add_field(
                name="Actions",
                value=(
                    "**Purger** — Applique les règles du mode pour éjecter les membres non éligibles.\n"
                    "**Transférer** — Donne la propriété du salon à un membre présent.\n"
                    "**Supprimer** — Ferme immédiatement le salon dynamique."
                ),
                inline=False,
            )
            await interaction.response.send_message(embed=help_embed, ephemeral=True)

        async def _set_mode(self, interaction: discord.Interaction, new_mode: str):
            rm = manager.room_meta.get(meta.channel_id)
            if not rm:
                await interaction.response.send_message("Meta introuvable", ephemeral=True)
                return
            channel, guild = self._resolve_channel_and_guild(rm)
            if not isinstance(channel, discord.VoiceChannel) or not isinstance(guild, discord.Guild):
                await interaction.response.send_message("Channel introuvable", ephemeral=True)
                return

            if new_mode == "conference":
                rm.conference_allowed = {m.id for m in channel.members}
                if rm.creator_id:
                    rm.conference_allowed.add(rm.creator_id)
            else:
                rm.conference_allowed.clear()

            rm.mode = new_mode

            try:
                await manager.apply_room_permissions(rm, guild)
            except Exception:
                await interaction.response.send_message("Erreur lors de la mise à jour des permissions", ephemeral=True)
                return

            creator_member = guild.get_member(rm.creator_id) if rm.creator_id else None
            new_embed = build_control_embed(rm, channel, creator_member)
            new_view = build_control_view(manager, rm)
            try:
                if interaction.response.is_done():
                    await interaction.followup.send("Mode modifié.", ephemeral=True)
                else:
                    await interaction.response.edit_message(embed=new_embed, view=new_view)
            except Exception:
                await interaction.followup.send("Mode mis à jour.", ephemeral=True)

            await self._refresh_panel(rm, guild)

        async def _open_user_select(self, interaction: discord.Interaction, list_type: str, action: str):
            rm = manager.room_meta.get(meta.channel_id)
            if not rm:
                await interaction.response.send_message("Meta introuvable", ephemeral=True)
                return

            parent_view = self

            class SelectUsersView(discord.ui.View):
                def __init__(self, *, timeout: Optional[float] = 60):
                    super().__init__(timeout=timeout)
                    self.list_type = list_type
                    self.action = action
                    ch, g = parent_view._resolve_channel_and_guild(rm)
                    self.voice_channel = ch if isinstance(ch, discord.VoiceChannel) else None
                    self.guild = g if isinstance(g, discord.Guild) else None

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
                                guild = self.guild or parent_view._resolve_channel_and_guild(_rm)[1]
                                await parent_view._apply_permissions(_rm, guild)
                                await parent_view._refresh_panel(_rm, guild)
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
                            member = self.guild.get_member(uid) if self.guild else None
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
                                guild = self.guild or parent_view._resolve_channel_and_guild(_rm)[1]
                                await parent_view._apply_permissions(_rm, guild)
                                await parent_view._refresh_panel(_rm, guild)
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

        async def _open_transfer_dialog(self, interaction: discord.Interaction, rm):
            channel, guild = self._resolve_channel_and_guild(rm)
            if not isinstance(channel, discord.VoiceChannel) or not isinstance(guild, discord.Guild):
                await interaction.response.send_message("Canal introuvable", ephemeral=True)
                return

            candidates = [m for m in channel.members if m.id != rm.creator_id]
            if not candidates:
                await interaction.response.send_message("Personne d'autre dans le salon.", ephemeral=True)
                return

            parent_view = self

            class TransferOwnershipView(discord.ui.View):
                def __init__(self, *, timeout: Optional[float] = 60):
                    super().__init__(timeout=timeout)
                    options: list[discord.SelectOption] = []
                    for member in candidates[:25]:
                        label = member.display_name[:100]
                        desc = f"{member.name}"[:100]
                        options.append(discord.SelectOption(label=label, value=str(member.id), description=desc))
                    select = discord.ui.Select(
                        placeholder="Choisir le nouveau propriétaire",
                        min_values=1,
                        max_values=1,
                        options=options,
                    )

                    async def on_select(sel_inter: discord.Interaction):
                        new_owner_id = int(select.values[0])
                        try:
                            await manager.transfer_room_ownership(rm, new_owner_id, guild)
                            await parent_view._refresh_panel(rm, guild)
                        except Exception:
                            await sel_inter.response.send_message("Transfert impossible.", ephemeral=True)
                            return
                        try:
                            await sel_inter.response.edit_message(
                                content=f"Propriété transférée à <@{new_owner_id}>.",
                                view=None,
                            )
                        except Exception:
                            pass

                    select.callback = on_select  # type: ignore[assignment]
                    self.add_item(select)

            try:
                await interaction.response.send_message(
                    content="Sélectionnez le nouveau propriétaire",
                    view=TransferOwnershipView(),
                    ephemeral=True,
                )
            except discord.InteractionResponded:
                await interaction.followup.send("Impossible d'ouvrir la sélection.", ephemeral=True)

    return ControlView()

