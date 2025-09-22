"""
Commandes slash `/autorole` : create, add, remove, list, link, delete, modify.

Implémentation MVP complète : la logique métier est déléguée à `views/autorole.py` (UI) et `db/autorole.py` (persistance).
"""
from __future__ import annotations

import re
import discord
from discord import app_commands
import logging

from core.permissions import require_perms, ADMINISTRATOR
from db import autorole as db
from views import autorole as ui

logger = logging.getLogger(__name__)

autorole = app_commands.Group(name="autorole", description="Gestion des autoroles")

ROLE_ID_RE = re.compile(r"^(<@&)?(\d{15,25})>?$")


async def _group_choices(interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
    """
    Retourne jusqu'à 25 choix de groupes filtrés par sous-chaîne pour l'autocomplétion.
    """
    if not interaction.guild:
        return []
    pool = getattr(interaction.client, 'db_pool', None)
    if pool is None:
        return []
    try:
        groups = await db.list_groups(pool, interaction.guild.id)
    except Exception:
        return []
    cur = (current or '').lower()
    out: list[app_commands.Choice[str]] = []
    for g in groups:
        name = str(g['name'])
        if cur and cur not in name.lower():
            continue
        out.append(app_commands.Choice(name=name[:100], value=name))
        if len(out) >= 25:
            break
    return out


def _parse_roles_arg(guild: discord.Guild, text: str | None):
    roles: list[int] = []
    if not text:
        return roles
    for tok in text.split():
        m = ROLE_ID_RE.match(tok)
        if m:
            rid = int(m.group(2))
            if guild.get_role(rid):
                roles.append(rid)
    # Déduplication en préservant l'ordre
    seen = set()
    out = []
    for r in roles:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


def _parse_emojis_arg(text: str | None, count: int):
    if not text:
        return [None] * count
    # Sépare par virgule ou point-virgule
    parts = re.split(r"[,;]", text)
    parts = [p.strip() or None for p in parts]
    # pad or trim to count
    if len(parts) < count:
        parts += [None] * (count - len(parts))
    return parts[:count]


def _bot_role_position_ok(guild: discord.Guild, role_id: int) -> bool:
    # Vérifie que le bot peut gérer le rôle (position dans la hiérarchie Discord)
    me = guild.me
    role = guild.get_role(role_id)
    return bool(me and role and (me.top_role > role))


@autorole.command(name="create", description="Créer un groupe d'autoroles")
@app_commands.describe(
    nom_groupe="Nom unique du groupe (par serveur)",
    liste_roles="Mentions ou IDs de rôles séparés par espaces (ex: @Rouge 123…)",
    liste_emoji="Emojis séparés par , ou ; (trous autorisés: ,,)",
    multi="Autoriser plusieurs rôles à la fois (false => max=1)",
    max="Limite de rôles attribuables simultanément (0 = illimité)",
    feedback="Envoyer un message de confirmation après sélection (ON par défaut)"
)
@require_perms(ADMINISTRATOR, message="Admin requis (bit 8)")
async def create(inter: discord.Interaction, nom_groupe: str, liste_roles: str | None = None, liste_emoji: str | None = None, multi: bool | None = True, max: int | None = 0, feedback: bool | None = True):
    if not inter.guild:
        await inter.response.send_message("Guild requise", ephemeral=True)
        return
    pool = getattr(inter.client, 'db_pool', None)
    if pool is None:
        await inter.response.send_message("DB non configurée", ephemeral=True)
        return
    await inter.response.defer(ephemeral=True)
    roles = _parse_roles_arg(inter.guild, liste_roles)
    emojis = _parse_emojis_arg(liste_emoji, len(roles))
    if not roles:
        await inter.followup.send("Aucun rôle valide.", ephemeral=True)
        return
    if multi is False:
        max = 1
    rec = await db.create_group(pool, inter.guild.id, nom_groupe, bool(multi), int(max or 0), bool(feedback if feedback is not None else True))
    if not rec:
        await inter.followup.send("Groupe déjà existant.", ephemeral=True)
        return
    gid = rec['id']
    # insert items
    for idx, rid in enumerate(roles, start=1):
        if not _bot_role_position_ok(inter.guild, rid):
            await inter.followup.send(f"Rôle trop haut: <@&{rid}> — ignoré", ephemeral=True)
            continue
        emoji = emojis[idx-1] if idx-1 < len(emojis) else None
        try:
            await db.add_item(pool, gid, rid, emoji, position=idx)
        except Exception:
            logger.exception("Add item failed")
    await inter.followup.send(f"Groupe créé: {nom_groupe} ({len(roles)} rôles)", ephemeral=True)


@create.autocomplete('nom_groupe')
async def ac_nom_groupe_create(interaction: discord.Interaction, current: str):
    return await _group_choices(interaction, current)


@autorole.command(name="add", description="Ajouter un rôle au groupe")
@app_commands.describe(
    nom_groupe="Nom du groupe cible",
    role="Rôle à ajouter",
    emoji="Emoji associé (optionnel)",
    emplacement="Position (1 = en tête). Laisser vide pour ajouter en fin"
)
@require_perms(ADMINISTRATOR)
async def add(inter: discord.Interaction, nom_groupe: str, role: discord.Role, emoji: str | None = None, emplacement: int | None = None):
    if not inter.guild:
        await inter.response.send_message("Guild requise", ephemeral=True)
        return
    pool = getattr(inter.client, 'db_pool', None)
    if pool is None:
        await inter.response.send_message("DB non configurée", ephemeral=True)
        return
    grp = await db.get_group(pool, inter.guild.id, nom_groupe)
    if not grp:
        await inter.response.send_message("Groupe introuvable.", ephemeral=True)
        return
    if not _bot_role_position_ok(inter.guild, role.id):
        await inter.response.send_message("Rôle trop haut.", ephemeral=True)
        return
    try:
        await db.add_item(pool, grp['id'], role.id, emoji, emplacement)
    except Exception:
        await inter.response.send_message("Conflit (doublon rôle/position)", ephemeral=True)
        return
    await inter.response.send_message("Ajouté.", ephemeral=True)


@add.autocomplete('nom_groupe')
async def ac_nom_groupe_add(interaction: discord.Interaction, current: str):
    return await _group_choices(interaction, current)


@autorole.command(name="remove", description="Retirer mapping par rôle ou emoji")
@app_commands.describe(
    nom_groupe="Nom du groupe",
    cible="Rôle (@mention/ID) ou emoji à retirer"
)
@require_perms(ADMINISTRATOR)
async def remove(inter: discord.Interaction, nom_groupe: str, cible: str):
    if not inter.guild:
        await inter.response.send_message("Guild requise", ephemeral=True)
        return
    pool = getattr(inter.client, 'db_pool', None)
    if pool is None:
        await inter.response.send_message("DB non configurée", ephemeral=True)
        return
    grp = await db.get_group(pool, inter.guild.id, nom_groupe)
    if not grp:
        await inter.response.send_message("Groupe introuvable.", ephemeral=True)
        return
    m = ROLE_ID_RE.match(cible)
    if m:
        rid = int(m.group(2))
        await db.remove_item_by_role(pool, grp['id'], rid)
    else:
        await db.remove_item_by_emoji(pool, grp['id'], cible)
    await inter.response.send_message("Retiré.", ephemeral=True)


@remove.autocomplete('nom_groupe')
async def ac_nom_groupe_remove(interaction: discord.Interaction, current: str):
    return await _group_choices(interaction, current)


@autorole.command(name="list", description="Lister groupes ou contenu d’un groupe")
@app_commands.describe(nom_groupe="Nom du groupe (vide => tous)")
async def list_cmd(inter: discord.Interaction, nom_groupe: str | None = None):
    if not inter.guild:
        await inter.response.send_message("Guild requise", ephemeral=True)
        return
    pool = getattr(inter.client, 'db_pool', None)
    if pool is None:
        await inter.response.send_message("DB non configurée", ephemeral=True)
        return
    if not nom_groupe:
        groups = await db.list_groups(pool, inter.guild.id)
        lines = []
        for g in groups:
            state = "lié" if g['linked_message_id'] else "non lié"
            try:
                fb = bool(g['feedback'])
            except Exception:
                fb = True
            lines.append(f"• {g['name']} — multi={g['multi']} max={g['max']} feedback={fb} — {state}{' (cassé)' if g['broken'] else ''}")
        await inter.response.send_message("\n".join(lines) or "Aucun groupe.", ephemeral=True)
        return
    grp = await db.get_group(pool, inter.guild.id, nom_groupe)
    if not grp:
        await inter.response.send_message("Groupe introuvable.", ephemeral=True)
        return
    items = await db.list_items(pool, grp['id'])
    lines = [f"index | role | emoji"]
    for idx, it in enumerate(items, start=1):
        lines.append(f"{idx} | <@&{it['role_id']}> | {it['emoji'] or '-'}")
    target = f"# {inter.guild.get_channel(grp['channel_id']).mention}" if grp['channel_id'] else "(non lié)"  # type: ignore
    await inter.response.send_message("\n".join(lines) + f"\nCible: {target}", ephemeral=True)


@list_cmd.autocomplete('nom_groupe')
async def ac_nom_groupe_list(interaction: discord.Interaction, current: str):
    return await _group_choices(interaction, current)


@autorole.command(name="link", description="Lier à un message / créer panneau")
@app_commands.describe(
    nom_groupe="Nom du groupe",
    message="ID ou lien d’un message existant (laisser vide pour créer un panneau)"
)
@require_perms(ADMINISTRATOR)
async def link(inter: discord.Interaction, nom_groupe: str, message: str | None = None):
    if not inter.guild or not isinstance(inter.channel, discord.TextChannel):
        await inter.response.send_message("Salon texte requis", ephemeral=True)
        return
    pool = getattr(inter.client, 'db_pool', None)
    if pool is None:
        await inter.response.send_message("DB non configurée", ephemeral=True)
        return
    grp = await db.get_group(pool, inter.guild.id, nom_groupe)
    if not grp:
        await inter.response.send_message("Groupe introuvable.", ephemeral=True)
        return
    items = await db.list_items(pool, grp['id'])
    if not items:
        await inter.response.send_message("Aucun rôle dans le groupe.", ephemeral=True)
        return
    await inter.response.defer(ephemeral=True)
    # Try fetch message
    target_message: discord.Message | None = None
    if message:
        try:
            if message.isdigit():
                target_message = await inter.channel.fetch_message(int(message))
            else:
                # attempt parse link
                parts = message.split('/')
                mid = int(parts[-1])
                target_message = await inter.channel.fetch_message(mid)
        except Exception:
            target_message = None
    # build UI per rules
    count = len(items)
    view: Optional[discord.ui.View] = None
    # Pas de pagination; on affiche 1 page logique
    embed = ui.build_group_embed(grp['name'], grp['multi'], grp['max'], page=0, pages=1)
    if count == 1:
        # Demande label et style (couleur) pour le bouton
        # 1) Label
        await inter.followup.send("Texte du bouton ?\nRépondez 'default' pour utiliser le texte par défaut, ou 'cancel' pour annuler.", ephemeral=True)
        label: str | None = None
        try:
            msg = await inter.client.wait_for(
                'message', timeout=60.0,
                check=lambda m: m.author.id == inter.user.id and m.channel.id == inter.channel.id,
            )
            content = (msg.content or '').strip()
            low = content.lower()
            if low in {"cancel", "annuler"}:
                await inter.followup.send("Annulé.", ephemeral=True)
                return
            if low in {"default", "defaut", "skip"}:
                label = None
            else:
                label = content
        except Exception:
            label = None
        # 2) Style
        # Options supportées: primary, secondary, success, danger ou 1/2/3/4
        await inter.followup.send("Couleur du bouton ? (primary, secondary, success, danger | 1/2/3/4)\nRépondez 'default' pour primary.", ephemeral=True)
        style_map = {
            '1': 1, 'primary': 1, 'primaire': 1, 'blurple': 1,
            '2': 2, 'secondary': 2, 'secondaire': 2, 'gris': 2,
            '3': 3, 'success': 3, 'vert': 3,
            '4': 4, 'danger': 4, 'rouge': 4,
        }
        style_val: int = 1
        try:
            msg2 = await inter.client.wait_for(
                'message', timeout=60.0,
                check=lambda m: m.author.id == inter.user.id and m.channel.id == inter.channel.id,
            )
            choice = (msg2.content or '').strip().lower()
            if choice in {"default", "defaut", "skip", ""}:
                style_val = 1
            else:
                style_val = style_map.get(choice, 1)
        except Exception:
            style_val = 1
        # Persiste ces préférences pour la réinscription des vues persistantes
        try:
            await db.update_group(pool, grp['id'], button_label=label, button_style=style_val)
        except Exception:
            logger.exception("Autorole: échec maj label/style")
        view = ui.AutoroleButton(role_id=int(items[0]['role_id']), multi=bool(grp['multi']), guild_id=inter.guild.id, group_id=int(grp['id']), label=label, style=style_val)
    elif 2 <= count <= 25:
        view = ui.AutoroleSelect(group_name=grp['name'], group_id=int(grp['id']), items=items, multi=bool(grp['multi']), max_value=int(grp['max']), guild=inter.guild)
    else:
        # Pour >25, utiliser plusieurs Selects en parallèle plutôt que la pagination
        view = ui.AutoroleMultiSelect(group_name=grp['name'], group_id=int(grp['id']), items=items, multi=bool(grp['multi']), max_value=int(grp['max']), guild=inter.guild)
    try:
        if target_message:
            # Copy content and attach UI below
            content = target_message.content or None
            out = await inter.channel.send(content=content, view=view)
            await db.update_group(pool, grp['id'], linked_message_id=out.id, channel_id=inter.channel.id, broken=False)
        else:
            out = await inter.channel.send(embed=embed, view=view)
            await db.update_group(pool, grp['id'], linked_message_id=out.id, channel_id=inter.channel.id, broken=False)
        await inter.followup.send("Lié.", ephemeral=True)
    except Exception:
        logger.exception("Link failed")
        await db.update_group(pool, grp['id'], broken=True)
        await inter.followup.send("Echec lien.", ephemeral=True)


@link.autocomplete('nom_groupe')
async def ac_nom_groupe_link(interaction: discord.Interaction, current: str):
    return await _group_choices(interaction, current)


@autorole.command(name="delete", description="Supprimer un groupe")
@app_commands.describe(nom_groupe="Nom du groupe à supprimer")
@require_perms(ADMINISTRATOR)
async def delete(inter: discord.Interaction, nom_groupe: str):
    if not inter.guild:
        await inter.response.send_message("Guild requise", ephemeral=True)
        return
    pool = getattr(inter.client, 'db_pool', None)
    if pool is None:
        await inter.response.send_message("DB non configurée", ephemeral=True)
        return
    # try cleanup message
    grp = await db.get_group(pool, inter.guild.id, nom_groupe)
    if grp and grp['channel_id'] and grp['linked_message_id']:
        ch = inter.guild.get_channel(int(grp['channel_id']))
        if isinstance(ch, discord.TextChannel):
            try:
                msg = await ch.fetch_message(int(grp['linked_message_id']))
                await msg.edit(view=None)
            except Exception:
                pass
    await db.delete_group(pool, inter.guild.id, nom_groupe)
    await inter.response.send_message("Supprimé.", ephemeral=True)


@delete.autocomplete('nom_groupe')
async def ac_nom_groupe_delete(interaction: discord.Interaction, current: str):
    return await _group_choices(interaction, current)


@autorole.command(name="modify", description="Modifier roles | emojis | multi | max")
@app_commands.describe(
    nom_groupe="Nom du groupe",
    cible="Champ à modifier (roles | emojis | multi | max | feedback)",
    valeur="Nouvelle valeur. Si vide, répondez au prochain message (tapez 'cancel' pour annuler)"
)
@app_commands.choices(
    cible=[
        app_commands.Choice(name="roles", value="roles"),
        app_commands.Choice(name="emojis", value="emojis"),
        app_commands.Choice(name="multi", value="multi"),
        app_commands.Choice(name="max", value="max"),
        app_commands.Choice(name="feedback", value="feedback"),
    ]
)
@require_perms(ADMINISTRATOR)
async def modify(inter: discord.Interaction, nom_groupe: str, cible: str, valeur: str | None = None):
    if not inter.guild:
        await inter.response.send_message("Guild requise", ephemeral=True)
        return
    pool = getattr(inter.client, 'db_pool', None)
    if pool is None:
        await inter.response.send_message("DB non configurée", ephemeral=True)
        return
    grp = await db.get_group(pool, inter.guild.id, nom_groupe)
    if not grp:
        await inter.response.send_message("Groupe introuvable.", ephemeral=True)
        return
    if valeur is None:
        await inter.response.send_message("Envoyez la nouvelle valeur dans le prochain message (ou 'cancel' pour annuler).", ephemeral=True)
        try:
            msg = await inter.client.wait_for(
                'message',
                timeout=60.0,
                check=lambda m: m.author.id == inter.user.id and m.channel.id == inter.channel.id,
            )
            if msg.content.strip().lower() in {"cancel", "annuler"}:
                await inter.followup.send("Annulé.", ephemeral=True)
                return
            valeur = msg.content
        except Exception:
            await inter.followup.send("Timeout.", ephemeral=True)
            return
    if cible == 'multi':
        new_multi = str(valeur).lower() in ('1','true','yes','y','on')
        await db.update_group(pool, grp['id'], multi=new_multi, max_value=(1 if not new_multi else grp['max']))
        await inter.response.send_message("MAJ ok.", ephemeral=True)
        return
    if cible == 'max':
        try:
            new_max = max(0, int(valeur))
        except Exception:
            await inter.response.send_message("Entier requis.", ephemeral=True)
            return
        await db.update_group(pool, grp['id'], max_value=new_max)
        await inter.response.send_message("MAJ ok.", ephemeral=True)
        return
    if cible == 'feedback':
        new_feedback = str(valeur).lower() in ('1','true','yes','y','on')
        await db.update_group(pool, grp['id'], feedback=new_feedback)
        await inter.response.send_message("MAJ ok.", ephemeral=True)
        return
    items = await db.list_items(pool, grp['id'])
    if cible == 'roles':
        roles = _parse_roles_arg(inter.guild, valeur)
        # replace all: delete then add with same emojis
        emojis = [it['emoji'] for it in items]
        await db.delete_group(pool, inter.guild.id, nom_groupe)
        # Préserve aussi le paramètre feedback lors de la recréation
        try:
            fb_val = bool(grp['feedback'])
        except Exception:
            fb_val = True
        rec = await db.create_group(pool, inter.guild.id, nom_groupe, grp['multi'], grp['max'], fb_val)
        if rec:
            for idx, rid in enumerate(roles, start=1):
                em = emojis[idx-1] if idx-1 < len(emojis) else None
                await db.add_item(pool, rec['id'], rid, em, idx)
        await inter.response.send_message("MAJ ok.", ephemeral=True)
        return
    if cible == 'emojis':
        # Traite la valeur comme une liste d'emojis séparés par , ou ;
        em_list = [e for e in (re.split(r"[,;]", valeur) if valeur else [])]
        em_list = [e.strip() or None for e in em_list]
        # align length
        if len(em_list) < len(items):
            em_list += [None] * (len(items)-len(em_list))
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("DELETE FROM autorole_item WHERE group_id=$1", grp['id'])
                for idx, it in enumerate(items, start=1):
                    await conn.execute("INSERT INTO autorole_item(group_id, role_id, emoji, position) VALUES($1,$2,$3,$4)", grp['id'], it['role_id'], em_list[idx-1] if idx-1 < len(em_list) else None, idx)
        await inter.response.send_message("MAJ ok.", ephemeral=True)
        return
    await inter.response.send_message("Cible inconnue.", ephemeral=True)


@modify.autocomplete('nom_groupe')
async def ac_nom_groupe_modify(interaction: discord.Interaction, current: str):
    return await _group_choices(interaction, current)


class AutoroleRuntime:
    async def handle_toggle(self, interaction: discord.Interaction, role_id: int, multi: bool, group_id: int | None = None):
        member = interaction.guild.get_member(interaction.user.id) if interaction.guild else None
        role = interaction.guild.get_role(role_id) if interaction.guild else None
        if not isinstance(member, discord.Member) or not role:
            await interaction.followup.send("Introuvable.", ephemeral=True)
            return
        if role >= interaction.guild.me.top_role:  # type: ignore
            await interaction.followup.send("Rôle trop haut.", ephemeral=True)
            return
        has = role in member.roles
        try:
            if has:
                await member.remove_roles(role, reason="autorole toggle")
            else:
                # multi constraint handled on select handler for group; here single button is a single role
                await member.add_roles(role, reason="autorole toggle")
            # Respecte le paramètre feedback (par groupe) si group_id fourni
            pool = getattr(interaction.client, 'db_pool', None)
            do_feedback = True
            if pool and group_id:
                try:
                    grp = await db.get_group_by_id(pool, int(group_id))
                    if grp is not None:
                        try:
                            do_feedback = bool(grp['feedback'])
                        except Exception:
                            do_feedback = True
                except Exception:
                    do_feedback = True
            if do_feedback:
                await interaction.followup.send("OK", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("Permissions insuffisantes pour gérer ce rôle.", ephemeral=True)
        except Exception:
            logger.exception("Autorole toggle failed")
            await interaction.followup.send("Echec.", ephemeral=True)

    async def handle_select(self, interaction: discord.Interaction, group_name: str, role_ids: list[int], multi: bool, max_value: int, scope_ids: list[int] | None = None):
        member = interaction.guild.get_member(interaction.user.id) if interaction.guild else None
        if not isinstance(member, discord.Member):
            await interaction.followup.send("Introuvable.", ephemeral=True)
            return
        # enforce hierarchy and constraints
        roles = [interaction.guild.get_role(rid) for rid in role_ids]  # type: ignore
        roles = [r for r in roles if r and r < interaction.guild.me.top_role]  # type: ignore

        # Determine group roles (for multi/max and cleanup)
        pool = getattr(interaction.client, 'db_pool', None)
        if pool is None:
            await interaction.followup.send("DB non configurée.", ephemeral=True)
            return
        try:
            grp = await db.get_group(pool, interaction.guild.id, group_name)
        except Exception:
            logger.exception("Autorole: get_group failed")
            await interaction.followup.send("Erreur interne (groupe).", ephemeral=True)
            return
        if not grp:
            await interaction.followup.send("Groupe introuvable.", ephemeral=True)
            return
        try:
            items = await db.list_items(pool, grp['id'])
        except Exception:
            logger.exception("Autorole: list_items failed")
            await interaction.followup.send("Erreur interne (items).", ephemeral=True)
            return
        group_role_ids = {int(it['role_id']) for it in items}

        # Compute additions/removals
        to_add: list[discord.Role] = []
        to_remove: list[discord.Role] = []

        # If a scope is provided (roles present in the interacted select), remove any currently held roles in that scope that are not selected now
        if scope_ids is not None:
            scope_set = set(scope_ids)
            selected_set = set(role_ids)
            for r in member.roles:
                if r.id in scope_set and r.id not in selected_set and r.id in group_role_ids and r < interaction.guild.me.top_role:  # type: ignore
                    to_remove.append(r)

        if roles:
            if not multi:
                # Remove any other roles from the group (keep only first selected)
                to_remove.extend([r for r in member.roles if r.id in group_role_ids and (not scope_ids or r.id not in {rr.id for rr in roles})])
                to_add = roles[:1]
            else:
                # Enforce max across the entire group, accounting for roles being removed in this same interaction (swap)
                current_ids = {r.id for r in member.roles if r.id in group_role_ids}
                add_candidates = [r for r in roles if r.id not in current_ids]
                if max_value and max_value > 0:
                    removed_ids = {r.id for r in to_remove}
                    effective_current = len(current_ids - removed_ids)
                    if effective_current + len(add_candidates) > max_value:
                        await interaction.followup.send(f"❌ Limite atteinte ({effective_current}/{max_value})", ephemeral=True)
                        return
                to_add = add_candidates

        if not to_add and not to_remove:
            # Respect feedback setting: if disabled, stay silent
            try:
                fb = bool(grp['feedback'])
            except Exception:
                fb = True
            if fb:
                await interaction.followup.send("Aucune modification.", ephemeral=True)
            return
        try:
            if to_remove:
                await member.remove_roles(*to_remove, reason="autorole select (deselection)")
            if to_add:
                await member.add_roles(*to_add, reason="autorole select")
            # Réponse conditionnelle selon feedback
            try:
                fb = bool(grp['feedback'])
            except Exception:
                fb = True
            if fb:
                await interaction.followup.send("OK", ephemeral=True)
        except discord.Forbidden:
            await interaction.followup.send("Permissions insuffisantes pour gérer ces rôles.", ephemeral=True)
        except Exception:
            logger.exception("Autorole select failed")
            await interaction.followup.send("Echec.", ephemeral=True)


def ensure_autorole_runtime(bot: discord.Client):
    """Garantit l'initialisation du runtime autorole sur le bot."""
    rt = getattr(bot, 'autorole_runtime', None)
    if not hasattr(rt, 'handle_select') or not hasattr(rt, 'handle_toggle'):
        bot.autorole_runtime = AutoroleRuntime()  # type: ignore


def register(bot: discord.Client):
    bot.tree.add_command(autorole)
    ensure_autorole_runtime(bot)

from typing import Iterable


async def ensure_autorole_views(bot: discord.Client) -> int:
    """Enregistre les vues persistantes pour tous les groupes liés au démarrage.

    Discord.py nécessite `bot.add_view(view)` pour les vues persistantes après reboot.
    On parcourt les serveurs, charge les groupes liés et enregistre la vue adéquate
    (Button / Select / MultiSelect) avec des custom_id stables.
    """
    pool = getattr(bot, 'db_pool', None)
    if pool is None:
        return 0
    # Itère sur les guilds connus par le client
    guilds: Iterable[discord.Guild] = getattr(bot, 'guilds', [])  # type: ignore
    ensure_autorole_runtime(bot)
    added = 0
    for guild in guilds:
        if not isinstance(guild, discord.Guild):
            continue
        try:
            groups = await db.list_groups(pool, guild.id)
        except Exception:
            logger.exception("Autorole: list_groups failed for guild %s", getattr(guild, 'id', '?'))
            continue
        for g in groups:
            try:
                if not g['linked_message_id'] or not g['channel_id']:
                    continue
                items = await db.list_items(pool, g['id'])
                if not items:
                    continue
                count = len(items)
                if count == 1:
                    label = None
                    style = None
                    try:
                        label = g['button_label']
                    except Exception:
                        label = None
                    try:
                        style = int(g['button_style']) if g['button_style'] is not None else None
                    except Exception:
                        style = None
                    v = ui.AutoroleButton(role_id=int(items[0]['role_id']), multi=bool(g['multi']), guild_id=guild.id, group_id=int(g['id']), label=label, style=style)
                elif 2 <= count <= 25:
                    v = ui.AutoroleSelect(group_name=str(g['name']), group_id=int(g['id']), items=items, multi=bool(g['multi']), max_value=int(g['max']), guild=guild)
                else:
                    v = ui.AutoroleMultiSelect(group_name=str(g['name']), group_id=int(g['id']), items=items, multi=bool(g['multi']), max_value=int(g['max']), guild=guild)
                bot.add_view(v)
                added += 1
            except Exception:
                try:
                    gname = str(g['name'])
                except Exception:
                    gname = '?'
                logger.exception("Autorole: echec add_view pour %s", gname)
    return added


__all__ = ["register", "ensure_autorole_runtime", "AutoroleRuntime", "ensure_autorole_views"]
