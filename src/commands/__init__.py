"""
Registre dynamique des commandes slash du bot Discord.

Convention :
- Chaque fichier de ce package (hors _*) expose une fonction `register(bot)`
	qui attache une ou plusieurs commandes au `bot.tree`.
- La fonction `load_all_commands(bot)` importe et exécute automatiquement tous les modules de commandes.
"""
from __future__ import annotations

import importlib
import pkgutil
import logging
import discord

logger = logging.getLogger(__name__)

async def load_all_commands(bot: discord.Client):
	for mod in pkgutil.iter_modules(__path__):  # type: ignore[name-defined]
		if mod.name.startswith('_'):
			continue
		full_name = f"{__name__}.{mod.name}"
		try:
			module = importlib.import_module(full_name)
			if hasattr(module, 'register'):
				reg = getattr(module, 'register')
				result = reg(bot)
				if hasattr(result, '__await__'):
					await result
				logger.debug("Commande chargée: %s", full_name)
		except Exception:  # noqa: BLE001
			logger.exception("Echec chargement commande %s", full_name)

__all__ = ["load_all_commands"]
