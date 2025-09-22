"""
Configuration centrale du bot Discord.

Ce module charge les variables d'environnement (.env) et prépare :
- Les intents Discord (message_content, members, presences)
- Le token du bot (BOT_TOKEN, obligatoire)
- L'URL de la base de données (DATABASE_URL, optionnelle)

Un warning est émis si BOT_TOKEN est absent pour détecter le problème avant le lancement du bot.
"""
from __future__ import annotations

import os
import logging
from dotenv import load_dotenv
import discord

load_dotenv()

logger = logging.getLogger(__name__)

INTENTS = discord.Intents.default()
INTENTS.message_content = True
INTENTS.members = True

# L'intent "presences" est privilégié ; activable via la variable d'environnement ENABLE_PRESENCES
_PRESENCES_ENV = (os.getenv("ENABLE_PRESENCES", "false") or "false").strip().lower()
INTENTS.presences = _PRESENCES_ENV in {"1", "true", "yes", "on"}

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")


# Avertit si le token du bot est absent
if not BOT_TOKEN:
    logger.warning("BOT_TOKEN manquant dans l'environnement")
