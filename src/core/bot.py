"""
Classe principale du bot Discord.

Responsabilités :
- Crée le client Discord et l'arbre de commandes slash.
- Initialise la base de données (pool + schéma) si configurée.
- Charge dynamiquement les fonctionnalités (voice hubs, db browser).
- Enregistre les commandes et événements globaux.

Note : L'initialisation asynchrone est centralisée dans `setup_hook`, appelé avant `on_ready`.
"""
from __future__ import annotations

import logging
import discord
from discord import app_commands

from core import config, db

logger = logging.getLogger(__name__)

class Bot(discord.Client):
    """
    Client Discord étendu, encapsulant l'état applicatif.

    Attributs principaux :
        tree : Arbre des commandes slash (CommandTree)
        db_pool : Pool asyncpg (None si aucune DB configurée)
    """


    def __init__(self):
        super().__init__(intents=config.INTENTS)
        self.tree = app_commands.CommandTree(self)
        self.db_pool = None  # Sera peuplé si DATABASE_URL défini
        self._autorole_views_registered = False

    async def setup_hook(self):
        """
        Initialise les sous-systèmes avant la mise en ligne.

        Séquence :
        1. Connexion et migration DB (si configurée)
        2. Chargement des fonctionnalités dépendantes de la DB
        3. Enregistrement des commandes et événements globaux
        """
        # Initialisation DB et schémas
        try:
            if config.DATABASE_URL:
                self.db_pool = await db.get_pool(config.DATABASE_URL)
                await db.ensure_schema(self.db_pool)
                # Autorole schema
                try:
                    from db import autorole as autorole_db  # import local pour éviter cycles
                    await autorole_db.ensure_schema(self.db_pool)
                    logger.info("Schéma autorole vérifié")
                except Exception:  # noqa: BLE001
                    logger.exception("Erreur init schéma autorole")
                # Welcome schema
                try:
                    from db import welcome as welcome_db  # type: ignore
                    await welcome_db.ensure_schema(self.db_pool)
                    logger.info("Schéma welcome vérifié")
                except Exception:  # noqa: BLE001
                    logger.exception("Erreur init schéma welcome")
                logger.info("DB prête")
        except Exception:  # noqa: BLE001
            logger.exception("Erreur init DB")
        # Features dépendantes DB
        if self.db_pool is not None:
            try:
                from core.voice_hubs.manager import setup_voice_hubs_manager  # type: ignore
                await setup_voice_hubs_manager(self, self.db_pool)
                logger.info("VoiceHubs manager initialisé")
            except Exception:  # noqa: BLE001
                logger.exception("Erreur init VoiceHubs manager")
        # Chargement commandes dynamiques
        try:
            from commands import load_all_commands  # type: ignore
            await load_all_commands(self)
            # S'assure que le runtime autorole est initialisé (les vues seront enregistrées après ready)
            try:
                from commands.autorole import ensure_autorole_runtime  # type: ignore
                ensure_autorole_runtime(self)
            except Exception:  # noqa: BLE001
                logger.exception("Erreur init runtime autorole")
        except Exception:  # noqa: BLE001
            logger.exception("Erreur chargement commandes dynamiques")
        # Events généraux
        try:
            from events.members import setup as setup_members  # type: ignore
            setup_members(self)
        except Exception:  # noqa: BLE001
            logger.exception("Erreur setup events")
        # Sync final
        try:
            await self.tree.sync()
            logger.info("Slash commands synchronisées")
        except Exception:  # noqa: BLE001
            logger.exception("Erreur sync slash commands")

    async def on_ready(self):
        """
        Log d'état lorsque le bot est prêt.
        S'assure que les vues autorole persistantes sont bien enregistrées.
        """
        logger.info("Connecté: %s (%s)", self.user, getattr(self.user, 'id', '?'))
        # Filet de sécurité: s'assurer que les vues autorole persistantes sont bien enregistrées
        if not self._autorole_views_registered:
            try:
                from commands.autorole import ensure_autorole_views  # type: ignore
                added = await ensure_autorole_views(self)
                self._autorole_views_registered = added > 0
                logger.info("Vues autorole persistantes enregistrées (on_ready)")
            except Exception:
                logger.exception("Erreur enregistrement vues autorole (on_ready)")

    async def close(self):  # type: ignore[override]
        """
        Fermeture propre du bot.
        Ajoute la fermeture du pool asyncpg si présent.
        Les commandes sont déjà synchronisées par discord.Client.close.
        """
        try:
            if self.db_pool is not None:
                await self.db_pool.close()  # type: ignore[union-attr]
                logger.info("Pool asyncpg fermé")
        except Exception:  # noqa: BLE001
            logger.exception("Erreur fermeture pool")
        await super().close()
