from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Set


@dataclass
class RoomMeta:
    """État en mémoire d'une room dynamique.

    mode:
        open    -> visible & accessible
        closed  -> visible, accès restreint (future whitelist)
        private -> invisible, accès liste blanche uniquement
    """

    channel_id: int
    creator_id: int
    mode: str  # 'open' | 'closed' | 'private'
    control_message_id: Optional[int] = None
    text_channel_id: Optional[int] = None
    whitelist: Set[int] = field(default_factory=set)
    blacklist: Set[int] = field(default_factory=set)
