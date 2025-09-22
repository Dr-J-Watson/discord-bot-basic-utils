"""
Entrée principale du bot Discord.

Ce script garantit que le dossier courant est ajouté à sys.path pour permettre les imports absolus
(core, commands, etc.), même si le lancement se fait via `python src/run.py`.
"""
from __future__ import annotations

import sys
import logging
import os

 # Ajoute dynamiquement le répertoire courant à sys.path si nécessaire
_CURRENT_DIR = os.path.dirname(__file__)
if _CURRENT_DIR not in sys.path:
    sys.path.insert(0, _CURRENT_DIR)

from core.logging_config import setup_logging  # noqa: E402
setup_logging()  # Initialise le logging global

from core import config, bot as bot_module  # noqa: E402


# Vérifie la présence du token Discord
if not config.BOT_TOKEN:
    raise SystemExit("BOT_TOKEN manquant")


# Instancie le client principal du bot
bot = bot_module.Bot()


# Démarre le bot si le script est exécuté directement
if __name__ == "__main__":
    try:
        bot.run(config.BOT_TOKEN)
    except KeyboardInterrupt:
        print("Arrêt manuel")
        sys.exit(0)
