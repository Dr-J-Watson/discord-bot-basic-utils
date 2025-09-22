"""
Configuration centralisée du logging pour le bot Discord.

Objectifs :
- Un seul setup idempotent (évite la duplication des handlers)
- Déduplication des messages identiques (utile en cas de retries)
- Format uniforme configurable via variables d'environnement
"""
from __future__ import annotations

import logging
import threading
import os

_INITIALIZED = False
_SEEN_LOCK = threading.Lock()
_SEEN_RECORDS = set()

DEFAULT_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
DEFAULT_FORMAT = '[%(asctime)s] %(levelname)s %(name)s: %(message)s'


class _DeduplicateFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401
        # Déduplication basée sur le message rendu (args interpolés)
        try:
            rendered = record.getMessage()
        except Exception:  # noqa: BLE001
            rendered = str(record.msg)
        key = (record.name, record.levelno, rendered)
        with _SEEN_LOCK:
            if key in _SEEN_RECORDS:
                return False
            _SEEN_RECORDS.add(key)
            # Limite la croissance mémoire (reset si trop gros)
            if len(_SEEN_RECORDS) > 5000:
                _SEEN_RECORDS.clear()
        return True


def setup_logging(force: bool = False) -> None:
    global _INITIALIZED
    if _INITIALIZED and not force:
        return

    root = logging.getLogger()
    if force:
        # Purge tous les handlers existants
        for h in list(root.handlers):
            root.removeHandler(h)
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.addFilter(_DeduplicateFilter())
        handler.setFormatter(logging.Formatter(DEFAULT_FORMAT))
        root.addHandler(handler)
    else:
        # Ajoute le filtre de déduplication à chaque handler existant
        for h in root.handlers:
            h.addFilter(_DeduplicateFilter())
    # Uniformise le format et le niveau de log
    for h in root.handlers:
        h.setFormatter(logging.Formatter(DEFAULT_FORMAT))
    root.setLevel(getattr(logging, DEFAULT_LEVEL, logging.INFO))
    _INITIALIZED = True


__all__ = ["setup_logging"]
