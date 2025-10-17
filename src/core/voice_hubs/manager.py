from __future__ import annotations

import asyncio
import logging
from typing import Dict, Set, Optional

import discord

from db import voice_hubs as db
from .models import RoomMeta
from views.voice_hubs import build_control_view, build_control_embed

logger = logging.getLogger(__name__)


class VoiceHubsManager:
    """Coordonne la logique des voice hubs (migré depuis features.voice_hubs.runtime.manager).

    Responsabilités:
        - Suivi des hubs et rooms dynamiques.
        - Création / suppression automatique selon activité.
        - Permissions selon le mode (placeholder pour évolutions futures).
        - Nettoyage & vérification d'intégrité.
    """

    def __init__(self, bot: discord.Client, pool):
        self.bot = bot
        self.pool = pool
        self.hubs: Set[int] = set()
        self.locks: Dict[int, asyncio.Lock] = {}
        self.dynamic_rooms: Set[int] = set()
        self.room_meta: Dict[int, RoomMeta] = {}

    async def load(self):
        await db.ensure_voice_hub_schema(self.pool)
        records = await db.fetch_active_hubs(self.pool)
        self.hubs = {r["id"] for r in records}
        for r in await db.fetch_all_rooms(self.pool):
            self.dynamic_rooms.add(r["id"])
        logger.info("VoiceHubs chargés: %s | Rooms: %s", len(self.hubs), len(self.dynamic_rooms))

    # ---------- utilitaires ----------
    def get_lock(self, hub_id: int) -> asyncio.Lock:
        lock = self.locks.get(hub_id)
        if lock is None:
            lock = asyncio.Lock()
            self.locks[hub_id] = lock
        return lock

    async def apply_room_permissions(self, meta: RoomMeta, guild: discord.Guild):
        channel = guild.get_channel(meta.channel_id)
        if not isinstance(channel, discord.VoiceChannel):
            return

        reason = f"Voice hub update ({meta.mode})"
        default_role = guild.default_role
        base_overwrite = channel.overwrites_for(default_role)

        # Mode-specific permissions for everyone
        if meta.mode == "open":
            base_overwrite.connect = True
            base_overwrite.view_channel = True
            base_overwrite.speak = None
        elif meta.mode == "closed":
            base_overwrite.connect = False
            base_overwrite.view_channel = True
            base_overwrite.speak = None
        elif meta.mode == "private":
            base_overwrite.connect = False
            base_overwrite.view_channel = False
            base_overwrite.speak = None
        elif meta.mode == "conference":
            base_overwrite.connect = True
            base_overwrite.view_channel = True
            base_overwrite.speak = False

        try:
            await channel.set_permissions(default_role, overwrite=base_overwrite, reason=reason)
        except Exception:  # noqa: BLE001
            logger.exception("Impossible de mettre à jour les permissions par défaut pour %s", channel.id)

        if meta.mode != "conference" and meta.conference_allowed:
            meta.conference_allowed.clear()

        allowed_ids = {meta.creator_id}
        allowed_ids.update(meta.whitelist)
        if meta.mode == "conference":
            allowed_ids.update(meta.conference_allowed)

        # Ne jamais garder en allowed des utilisateurs blacklistés
        allowed_ids.difference_update(meta.blacklist)

        tracked_ids = set(allowed_ids) | set(meta.blacklist) | set(meta.conference_allowed)
        if meta.creator_id:
            tracked_ids.add(meta.creator_id)

        async def set_member_overwrite(user_id: int, *, connect: Optional[bool] = None, view: Optional[bool] = None, speak: Optional[bool] = None):
            member = guild.get_member(user_id)
            if not isinstance(member, discord.Member):
                return
            overwrite = channel.overwrites_for(member)
            if connect is not None:
                overwrite.connect = connect
            if view is not None:
                overwrite.view_channel = view
            if speak is not None:
                overwrite.speak = speak
            try:
                await channel.set_permissions(member, overwrite=overwrite, reason=reason)
            except Exception:  # noqa: BLE001
                logger.debug("Impossible d'appliquer overwrite pour %s sur %s", user_id, channel.id)

        for uid in tracked_ids:
            if uid in meta.blacklist:
                await set_member_overwrite(
                    uid,
                    connect=False,
                    view=False if meta.mode == "private" else None,
                    speak=False,
                )
            elif uid in allowed_ids:
                await set_member_overwrite(
                    uid,
                    connect=True,
                    view=True,
                    speak=True if meta.mode == "conference" else None,
                )
            else:
                await set_member_overwrite(
                    uid,
                    connect=None,
                    view=None if meta.mode != "private" else False,
                    speak=None,
                )

        if not meta.conference_allowed:
            for target, _ in list(channel.overwrites.items()):
                if not isinstance(target, discord.Member):
                    continue
                if target.id in tracked_ids:
                    continue
                try:
                    await channel.set_permissions(target, overwrite=None, reason=reason)
                except Exception:  # noqa: BLE001
                    logger.debug("Impossible de nettoyer les permissions résiduelles pour %s", target.id)

    async def transfer_room_ownership(self, meta: RoomMeta, new_owner_id: int, guild: discord.Guild):
        channel = guild.get_channel(meta.channel_id)
        if not isinstance(channel, discord.VoiceChannel):
            raise RuntimeError("Canal introuvable pour le transfert")

        old_owner_id = meta.creator_id
        if new_owner_id == old_owner_id:
            return

        meta.creator_id = new_owner_id
        meta.blacklist.discard(new_owner_id)
        if meta.mode == "conference":
            meta.conference_allowed.add(new_owner_id)
            if old_owner_id not in meta.whitelist:
                meta.conference_allowed.discard(old_owner_id)

        await self.apply_room_permissions(meta, guild)

        allow_perms = discord.Permissions()
        allow_perms.update(
            manage_channels=True,
            move_members=True,
            mute_members=True,
            deafen_members=True,
            connect=True,
            speak=True,
            stream=True,
            priority_speaker=True,
            use_voice_activation=True,
        )

        new_member = guild.get_member(new_owner_id)
        if isinstance(new_member, discord.Member):
            try:
                overwrite = discord.PermissionOverwrite.from_pair(allow_perms, discord.Permissions.none())
                await channel.set_permissions(new_member, overwrite=overwrite, reason="Voice hub ownership transfer")
            except Exception:  # noqa: BLE001
                logger.exception("Impossible d'appliquer les permissions propriétaire pour %s", new_owner_id)

        if old_owner_id and old_owner_id != new_owner_id:
            old_member = guild.get_member(old_owner_id)
            if isinstance(old_member, discord.Member):
                try:
                    overwrite = channel.overwrites_for(old_member)
                    overwrite.manage_channels = None
                    overwrite.move_members = None
                    overwrite.mute_members = None
                    overwrite.deafen_members = None
                    overwrite.stream = None
                    overwrite.priority_speaker = None
                    overwrite.use_voice_activation = None
                    await channel.set_permissions(old_member, overwrite=overwrite, reason="Voice hub ownership transfer cleanup")
                except Exception:  # noqa: BLE001
                    logger.debug("Impossible de nettoyer les permissions de l'ancien propriétaire %s", old_owner_id)

        logger.info("Transfert de propriété du salon %s: %s -> %s", meta.channel_id, old_owner_id, new_owner_id)

    # ---------- hubs ----------
    async def add_hub(self, channel: discord.VoiceChannel):
        await db.insert_hub(self.pool, channel.id, channel.guild.id)
        self.hubs.add(channel.id)
        logger.info("Hub ajouté %s (guild %s)", channel.id, channel.guild.id)

    async def remove_hub(self, channel_id: int):
        if channel_id in self.hubs:
            await db.deactivate_hub(self.pool, channel_id)
            self.hubs.discard(channel_id)
            logger.info("Hub désactivé %s", channel_id)

    # ---------- rooms dynamiques ----------
    async def is_dynamic_room(self, channel_id: int) -> bool:
        if channel_id in self.dynamic_rooms:
            return True
        rec = await db.fetch_room(self.pool, channel_id)
        if rec:
            self.dynamic_rooms.add(channel_id)
            return True
        return False

    async def create_dynamic_room(self, member: discord.Member, hub_channel: discord.VoiceChannel):
        hub_id = hub_channel.id
        lock = self.get_lock(hub_id)
        async with lock:
            if not member.voice or member.voice.channel is None or member.voice.channel.id != hub_id:
                return
            # Vérifier plafond de rooms (max_rooms) si configuré
            try:
                hub_conf = await db.fetch_hub_config(self.pool, hub_id)
            except Exception:  # noqa: BLE001
                hub_conf = None
            max_rooms_allowed = None
            if hub_conf:
                # hub_conf est un Record asyncpg: accès par clé
                max_rooms_allowed = hub_conf.get("max_rooms") if hasattr(hub_conf, "get") else hub_conf["max_rooms"]
            if isinstance(max_rooms_allowed, int) and max_rooms_allowed > 0:
                try:
                    current_rooms = await db.count_rooms_for_hub(self.pool, hub_id)
                    if current_rooms >= max_rooms_allowed:
                        logger.debug("Plafond rooms atteint pour hub %s (%s/%s)", hub_id, current_rooms, max_rooms_allowed)
                        return
                except Exception:  # noqa: BLE001
                    pass
            sequence = await db.next_sequence_for_hub(self.pool, hub_id)
            pattern: Optional[str] = None
            user_limit: Optional[int] = None
            if hub_conf:
                pattern = hub_conf.get("naming_scheme") if hasattr(hub_conf, "get") else hub_conf["naming_scheme"]
                # NOTE: max_rooms != user_limit; ne pas réutiliser max_rooms comme user_limit salon
            if pattern:
                try:
                    name = pattern.format(user=member.name, display=member.display_name, n=sequence)
                except Exception:  # noqa: BLE001
                    name = f"Salon de {member.display_name}"
            else:
                name = f"Salon de {member.display_name}"
            try:
                overwrites = dict(hub_channel.overwrites)
                allow_perms = discord.Permissions()
                allow_perms.update(
                    manage_channels=True,
                    move_members=True,
                    mute_members=True,
                    deafen_members=True,
                    connect=True,
                    speak=True,
                    stream=True,
                    priority_speaker=True,
                    use_voice_activation=True,
                )
                overwrites[member] = discord.PermissionOverwrite.from_pair(allow_perms, discord.Permissions.none())
                new_channel = await hub_channel.guild.create_voice_channel(
                    name,
                    category=hub_channel.category,
                    overwrites=overwrites,
                    user_limit=user_limit if isinstance(user_limit, int) and user_limit > 0 else hub_channel.user_limit,
                    reason=f"Dynamic room for hub {hub_id}",
                )
            except Exception:  # noqa: BLE001
                logger.exception("Echec création salon dynamique")
                return
            try:
                await db.insert_room(self.pool, new_channel.id, hub_id, hub_channel.guild.id, member.id, sequence, name)
                self.dynamic_rooms.add(new_channel.id)
                await member.move_to(new_channel, reason="Move to dynamic room")
                meta = RoomMeta(channel_id=new_channel.id, creator_id=member.id, mode="open")
                self.room_meta[new_channel.id] = meta
                try:
                    await self.apply_room_permissions(meta, hub_channel.guild)
                except Exception:  # noqa: BLE001
                    logger.exception("Echec application permissions initiales pour %s", new_channel.id)
                await self._send_control_panel(new_channel, meta, member)
                logger.info("Dynamic voice créé %s pour hub %s", new_channel.id, hub_id)
            except Exception:  # noqa: BLE001
                logger.exception("Echec post-création dynamic room")
                try:
                    await new_channel.delete(reason="Rollback dynamic room")
                except Exception:  # noqa: BLE001
                    pass

    async def _send_control_panel(self, voice_channel: discord.VoiceChannel, meta: RoomMeta, creator: discord.Member):
        view = build_control_view(self, meta)
        embed = build_control_embed(meta, voice_channel, creator)
        
        send_ok = False

        # Tentative d'envoi dans le salon vocal (text-in-voice)
        try:
            perms = voice_channel.permissions_for(voice_channel.guild.me)  # type: ignore
            if perms and getattr(perms, "send_messages", True):
                msg = await voice_channel.send(embed=embed, view=view)  # type: ignore[attr-defined]
                meta.control_message_id = msg.id
                meta.text_channel_id = voice_channel.id
                meta.control_is_dm = False
                send_ok = True
        except Exception:
            logger.debug("Impossible d'envoyer le panneau de contrôle dans le salon vocal %s", voice_channel.id, exc_info=True)

        if not send_ok and isinstance(creator, discord.Member):
            try:
                dm = creator.dm_channel or await creator.create_dm()
                dm_view = build_control_view(self, meta)
                msg = await dm.send(embed=embed, view=dm_view)
                meta.control_message_id = msg.id
                meta.text_channel_id = dm.id
                meta.control_is_dm = True
                send_ok = True
            except Exception:
                logger.debug("Impossible d'envoyer le panneau de contrôle en DM pour %s", creator.id, exc_info=True)

    async def delete_dynamic_room_if_empty(self, channel: discord.VoiceChannel):
        if channel.id not in self.dynamic_rooms:
            return
        if channel.members:
            return
        try:
            await db.delete_room(self.pool, channel.id)
            self.dynamic_rooms.discard(channel.id)
            await channel.delete(reason="Empty dynamic room")
            self.room_meta.pop(channel.id, None)
            logger.info("Dynamic voice supprimé %s (vide)", channel.id)
        except Exception:  # noqa: BLE001
            logger.exception("Echec suppression dynamic room")

    # Placeholder pour évolutions (permissions avancées, modes, etc.)
    async def handle_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        before_channel = before.channel
        after_channel = after.channel
        if after_channel and after_channel.id in self.hubs and (not before_channel or before_channel.id != after_channel.id):
            await self.create_dynamic_room(member, after_channel)
        if before_channel and before_channel != after_channel:
            if await self.is_dynamic_room(before_channel.id):
                await self.delete_dynamic_room_if_empty(before_channel)

    async def handle_channel_delete(self, channel: discord.abc.GuildChannel):
        if isinstance(channel, discord.VoiceChannel):
            cid = channel.id
            if cid in self.hubs:
                await db.deactivate_hub(self.pool, cid)
                self.hubs.discard(cid)
                logger.info("Hub supprimé détecté %s -> désactivé en base", cid)
            elif cid in self.dynamic_rooms:
                await db.delete_room(self.pool, cid)
                self.dynamic_rooms.discard(cid)
                logger.info("Dynamic room supprimée manuellement %s -> purgée DB", cid)

    async def cleanup_orphans(self):
        existing_voice_ids = {ch.id for ch in self.bot.get_all_channels() if isinstance(ch, discord.VoiceChannel)}
        missing_hubs = [hid for hid in list(self.hubs) if hid not in existing_voice_ids]
        for hid in missing_hubs:
            try:
                await db.deactivate_hub(self.pool, hid)
            except Exception:  # noqa: BLE001
                pass
            self.hubs.discard(hid)

        removed_rooms = []
        for room_id in list(self.dynamic_rooms):
            if room_id not in existing_voice_ids:
                try:
                    await db.delete_room(self.pool, room_id)
                except Exception:  # noqa: BLE001
                    pass
                self.dynamic_rooms.discard(room_id)
                self.room_meta.pop(room_id, None)
                removed_rooms.append(room_id)

        emptied_now = []
        for room_id in list(self.dynamic_rooms):
            ch = self.bot.get_channel(room_id)
            if isinstance(ch, discord.VoiceChannel) and not ch.members:
                try:
                    await db.delete_room(self.pool, room_id)
                except Exception:  # noqa: BLE001
                    pass
                try:
                    await ch.delete(reason="Startup cleanup empty dynamic room")
                except Exception:  # noqa: BLE001
                    pass
                self.dynamic_rooms.discard(room_id)
                self.room_meta.pop(room_id, None)
                emptied_now.append(room_id)

        try:
            db_rooms = await db.fetch_all_rooms(self.pool)
            for rec in db_rooms:
                rid = rec["id"]
                hid = rec["hub_id"]
                if hid not in self.hubs:
                    ch = self.bot.get_channel(rid)
                    if isinstance(ch, discord.VoiceChannel):
                        try:
                            await ch.delete(reason="Orphan dynamic room (hub inactive)")
                        except Exception:  # noqa: BLE001
                            pass
                    try:
                        await db.delete_room(self.pool, rid)
                    except Exception:  # noqa: BLE001
                        pass
                    if rid in self.dynamic_rooms:
                        self.dynamic_rooms.discard(rid)
                    self.room_meta.pop(rid, None)
                    removed_rooms.append(rid)
        except Exception:  # noqa: BLE001
            logger.exception("Echec scan rooms DB pour cleanup")

        logger.info(
            "Cleanup orphelins -> hubs désactivés: %s | rooms supprimées (inexistantes/hub inactif): %s | rooms vidées supprimées: %s",
            len(missing_hubs),
            len(removed_rooms),
            len(emptied_now),
        )

    async def verify_integrity(self) -> dict:
        existing_voice_ids = {ch.id for ch in self.bot.get_all_channels() if isinstance(ch, discord.VoiceChannel)}
        active_hubs_db = {r["id"] for r in await db.fetch_active_hubs(self.pool)}
        hub_missing_channels = [hid for hid in active_hubs_db if hid not in existing_voice_ids]
        db_rooms = await db.fetch_all_rooms(self.pool)
        room_missing_channels = [r["id"] for r in db_rooms if r["id"] not in existing_voice_ids]
        rooms_with_inactive_hub = [r["id"] for r in db_rooms if r["hub_id"] not in active_hubs_db]
        return {
            "active_hubs_db": len(active_hubs_db),
            "hubs_loaded_runtime": len(self.hubs),
            "hub_missing_channels": hub_missing_channels,
            "room_missing_channels": room_missing_channels,
            "rooms_with_inactive_hub": rooms_with_inactive_hub,
            "dynamic_rooms_runtime": len(self.dynamic_rooms),
        }


async def setup_voice_hubs_manager(bot, pool):
    manager = VoiceHubsManager(bot, pool)
    await manager.load()

    @bot.event
    async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):  # type: ignore
        await manager.handle_voice_state_update(member, before, after)

    @bot.event
    async def on_guild_channel_delete(channel: discord.abc.GuildChannel):  # type: ignore
        await manager.handle_channel_delete(channel)

    async def _post_ready_cleanup():
        await bot.wait_until_ready()
        await manager.cleanup_orphans()
        try:
            report = await manager.verify_integrity()
            logger.info("Integrity report: %s", report)
        except Exception:  # noqa: BLE001
            logger.exception("Echec integrity report")

    bot.loop.create_task(_post_ready_cleanup())
    bot.voice_hubs = manager  # type: ignore
    return manager
