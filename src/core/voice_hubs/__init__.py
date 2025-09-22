"""Voice hubs core package.

Les imports sont effectués de manière lazy pour éviter d'exécuter du code
pendant l'initialisation globale si non nécessaire.
"""
from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # aide mypy/IDE sans exécuter les imports au runtime initial
	from .manager import VoiceHubsManager, setup_voice_hubs_manager  # noqa: F401
	from .models import RoomMeta  # noqa: F401

__all__ = ["VoiceHubsManager", "setup_voice_hubs_manager", "RoomMeta"]


def __getattr__(name: str):  # lazy resolution
	if name in {"VoiceHubsManager", "setup_voice_hubs_manager"}:
		mod = import_module("core.voice_hubs.manager")
		return getattr(mod, name)
	if name == "RoomMeta":
		mod = import_module("core.voice_hubs.models")
		return getattr(mod, name)
	raise AttributeError(name)
