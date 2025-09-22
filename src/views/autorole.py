"""
Composants UI pour la fonctionnalité Autorole.

Ce module fournit :
- AutoroleButton : bouton pour basculer un rôle (cas 1 rôle)
- AutoroleSelect : liste déroulante pour 2 à 25 rôles
- AutoroleMultiSelect : plusieurs listes déroulantes pour > 25 rôles

Contraintes Discord :
- Un Select (StringSelect) accepte 1 à 25 options maximum
- max_values ne doit pas dépasser le nombre d'options affichées
- Si aucune option valable n'est disponible (ex : rôles supprimés), le Select est désactivé avec une option factice
"""

from __future__ import annotations

import discord
from typing import Optional, Sequence

PRIMARY = discord.Color.blurple()


def build_group_embed(name: str, multi: bool, max_value: int, page: int, pages: int) -> discord.Embed:
    """Crée l'embed de titre pour un groupe d'autorole.

    Arguments:
        name: nom du groupe
        multi: sélection multiple autorisée
        max_value: limite de rôles sélectionnables (si multi)
        page: index de page courant (0-based)
        pages: nombre total de pages
    """
    e = discord.Embed(title=f"Autorole — {name}", color=PRIMARY)
    if pages > 1:
        e.set_footer(text=f"Page {page+1}/{pages}")
    return e


def parse_emoji(s: Optional[str]) -> Optional[str]:
    """Nettoie une chaîne d'emoji éventuelle (custom ou unicode)."""
    if not s:
        return None
    return s.strip()


def build_select_options(items: Sequence[dict], guild: discord.Guild):
    """Construit la liste d'options pour un Select à partir d'items de DB.

    - Ignore silencieusement les rôles manquants (supprimés côté serveur).
    - Tronque les labels à 100 caractères (limite Discord).
    - Coupe à 25 options max (limite Discord).
    """
    options: list[discord.SelectOption] = []
    for r in items:
        role = guild.get_role(int(r["role_id"]))
        if not role:
            # Skip missing roles silently in UI build
            continue
        label = role.name[:100]
        try:
            emoji_val = r["emoji"]
        except Exception:
            emoji_val = None
        emoji = parse_emoji(emoji_val)
        options.append(discord.SelectOption(label=label, value=str(role.id), emoji=emoji))
        if len(options) >= 25:
            break
    return options


class AutoroleButton(discord.ui.View):
    """Vue bouton pour basculer un seul rôle.

    Utilisé quand le groupe ne contient qu'un seul rôle.
    """
    def __init__(self, *, role_id: int, multi: bool, guild_id: int, group_id: int, label: Optional[str] = None, style: Optional[int] = None):
        super().__init__(timeout=None)
        self.role_id = role_id
        self.multi = multi
        self.group_id = group_id
        # Bouton persistant avec custom_id déterministe
        custom_id = f"autorole:btn:{guild_id}:{group_id}:{role_id}"
        # Style par défaut: primaire. Si style est un int valide dans ButtonStyle, on l'utilise
        btn_style = discord.ButtonStyle.primary
        try:
            if style is not None and int(style) in [s.value for s in discord.ButtonStyle]:
                btn_style = discord.ButtonStyle(int(style))
        except Exception:
            pass
        btn_label = label if (label and label.strip()) else "Toggle"
        btn = discord.ui.Button(label=btn_label, style=btn_style, custom_id=custom_id)

        async def _cb(interaction: discord.Interaction):  # type: ignore
            await interaction.response.defer(ephemeral=True, thinking=False)
            rt = getattr(interaction.client, 'autorole_runtime', None)
            handler = getattr(rt, 'handle_toggle', None)
            if not callable(handler):
                await interaction.followup.send("Autorole non initialisé. Réessayez.", ephemeral=True)
                return
            await handler(interaction, self.role_id, self.multi, self.group_id)

        btn.callback = _cb  # type: ignore
        self.add_item(btn)


class AutoroleSelect(discord.ui.View):
    """Vue Select pour 2 à 25 rôles.

    On ajuste max_values pour ne jamais dépasser le nombre d'options.
    Si aucune option n'est disponible (rôles manquants), on désactive le Select.
    """
    def __init__(self, *, group_name: str, group_id: int, items: Sequence[dict], multi: bool, max_value: int, guild: discord.Guild):
        super().__init__(timeout=None)
        # max théorique selon les paramètres (multi + limite max_value)
        base_max = 1 if not multi else max(1, min(25, max_value if max_value > 0 else len(items)))
        options = build_select_options(items, guild)
        # On pince max_values pour qu'il ne dépasse pas la taille réelle d'options
        clamped_max = min(base_max, max(1, len(options))) if options else 1
        # En cas d'absence d'options valides, on fournit une option factice et on désactive
        min_vals = 0 if multi else 1
        custom_id = f"autorole:sel:{guild.id}:{group_id}"
        select = discord.ui.Select(placeholder="Choisir un rôle", min_values=min_vals, max_values=clamped_max, options=options if options else [discord.SelectOption(label="Aucun rôle disponible", value="none")], custom_id=custom_id)
        if not options:
            select.disabled = True
        # Scope = rôles présents dans ce Select (pour gérer les désélections)
        scope_ids = [int(opt.value) for opt in options if str(opt.value).isdigit()]
        async def _cb(inter: discord.Interaction):  # type: ignore
            await inter.response.defer(ephemeral=True, thinking=False)
            role_ids = [int(v) for v in select.values]
            rt = getattr(inter.client, 'autorole_runtime', None)
            handler = getattr(rt, 'handle_select', None)
            if not callable(handler):
                await inter.followup.send("Autorole non initialisé. Réessayez.", ephemeral=True)
                return
            await handler(inter, group_name, role_ids, multi, max_value, scope_ids)
        select.callback = _cb  # type: ignore
        self.add_item(select)




class AutoroleMultiSelect(discord.ui.View):
    """Vue avec plusieurs Selects (2 à 4) répartissant les rôles de façon équilibrée.

    Utilisée pour éviter la pagination quand un groupe contient plus de 25 rôles.
    Chaque Select fonctionne indépendamment: à chaque modification, on applique
    l'action via le handler runtime avec uniquement les valeurs du Select modifié.
    Les contraintes (multi/max/hiérarchie) sont contrôlées côté runtime.
    """

    def __init__(self, *, group_name: str, group_id: int, items: Sequence[dict], multi: bool, max_value: int, guild: discord.Guild):
        super().__init__(timeout=None)
        self.group_name = group_name
        self.group_id = group_id
        self.items = list(items)
        self.multi = multi
        self.max_value = max_value
        self.guild = guild
        self._build()

    def _split_items(self) -> list[list[dict]]:
        # Détermine le nombre de Selects à afficher (2..4) selon le nombre d'items
        total = len(self.items)
        if total <= 25:
            return [self.items]
        if total <= 50:
            parts = 2
        elif total <= 75:
            parts = 3
        else:
            parts = 4
        # Répartition à peu près égale (max 25 par Select)
        chunks: list[list[dict]] = []
        per = max(1, min(25, (total + parts - 1) // parts))
        # On limite à 25 par chunk pour respecter la contrainte Discord
        start = 0
        for _ in range(parts):
            end = min(start + per, total)
            if start >= end:
                break
            chunks.append(self.items[start:end])
            start = end
        return chunks

    def _build(self):
        self.clear_items()
        chunks = self._split_items()
        for idx, chunk in enumerate(chunks, start=1):
            options = build_select_options(chunk, self.guild)
            # max théorique par composant en fonction du groupe
            base_max = 1 if not self.multi else max(1, min(25, self.max_value if self.max_value > 0 else len(chunk)))
            clamped_max = min(base_max, max(1, len(options))) if options else 1
            placeholder = f"Choisir un rôle ({idx}/{len(chunks)})"
            # min_values=0 pour ne pas forcer une sélection dans chaque liste
            custom_id = f"autorole:msel:{self.guild.id}:{self.group_id}:{idx}"
            select = discord.ui.Select(placeholder=placeholder, min_values=0, max_values=clamped_max,
                                       options=options if options else [discord.SelectOption(label="Aucun rôle disponible", value="none")], custom_id=custom_id)
            if not options:
                select.disabled = True

            async def _cb(inter: discord.Interaction, s=select, scope=[int(opt.value) for opt in options if str(opt.value).isdigit()]):  # type: ignore
                await inter.response.defer(ephemeral=True, thinking=False)
                # On applique uniquement les valeurs du Select modifié
                role_ids = [int(v) for v in s.values if v.isdigit()]
                # Même si rien n'est sélectionné, on doit éventuellement retirer des rôles de ce scope
                rt = getattr(inter.client, 'autorole_runtime', None)
                handler = getattr(rt, 'handle_select', None)
                if not callable(handler):
                    await inter.followup.send("Autorole non initialisé. Réessayez.", ephemeral=True)
                    return
                await handler(inter, self.group_name, role_ids, self.multi, self.max_value, scope)

            select.callback = _cb  # type: ignore
            self.add_item(select)
