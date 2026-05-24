"""In-process event bus used to fan out updates to WebSocket clients.

The pattern is intentionally minimal: a single asyncio Queue per subscriber.
Producers call ``broadcast(event)`` without awaiting any consumer. If a
subscriber is slow, its queue grows up to ``maxsize`` and overflow events are
dropped (we'd rather drop than block — clients will get the next event).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Literal

logger = logging.getLogger(__name__)

EventType = Literal[
    "display_changed",
    "queue_updated",
    "settings_changed",
    "photo_uploaded",
    "photo_deleted",
]


class EventBus:
    def __init__(self, queue_maxsize: int = 32) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._maxsize = queue_maxsize

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self._maxsize)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(q)

    def broadcast(self, event_type: EventType, payload: dict[str, Any] | None = None) -> None:
        event = {"type": event_type, "payload": payload or {}}
        dropped = 0
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                dropped += 1
        if dropped:
            logger.warning("Dropped %s event(s) for slow subscribers", dropped)
