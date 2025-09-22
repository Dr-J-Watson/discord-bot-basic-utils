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
        # Attempt embed build only if we can locate channel and creator context
        embed = None
        channel = voice_channel
        creator_member = creator
        if isinstance(channel, discord.VoiceChannel) and creator_member:
            embed = build_control_embed(meta, channel, creator_member)
        # 1) Essai direct: envoyer dans le salon vocal (text-in-voice)
        try:
            perms = voice_channel.permissions_for(voice_channel.guild.me)  # type: ignore
            if perms and getattr(perms, "send_messages", True) and embed:
                msg = await voice_channel.send(embed=embed, view=view)  # type: ignore[attr-defined]
                meta.control_message_id = msg.id
                meta.text_channel_id = voice_channel.id
                return
        except Exception:
            # Peut ne pas être activé ou permission manquante -> fallback
            pass

        # 2) Fallback: récupérer le salon ou thread avec le même ID et vérifier l'envoi possible
        target = None
        try:
            candidate = voice_channel.guild.get_channel_or_thread(voice_channel.id)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            candidate = None
        if candidate is not None:
            try:
                perms = candidate.permissions_for(voice_channel.guild.me)  # type: ignore
                if hasattr(candidate, "send") and perms and perms.send_messages:
                    target = candidate
            except Exception:  # noqa: BLE001
                target = None

        # 3) Dernier recours: premier salon textuel envoyable dans la même catégorie
        if target is None and voice_channel.category:
            for ch in voice_channel.category.channels:
                if isinstance(ch, discord.TextChannel):
                    try:
                        if ch.permissions_for(voice_channel.guild.me).send_messages:  # type: ignore
                            target = ch
                            break
                    except Exception:  # noqa: BLE001
                        continue
        if target is None:
            return
        try:
            if embed:
                msg = await target.send(embed=embed, view=view)
                meta.control_message_id = msg.id
                meta.text_channel_id = target.id
        except Exception:  # noqa: BLE001
            logger.exception("Echec envoi panneau contrôle")

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
