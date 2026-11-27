"""In-process event bus used to fan out updates to WebSocket clients.

The pattern is intentionally minimal: a single asyncio Queue per subscriber.
Producers call ``broadcast(event)`` without awaiting any consumer. If a
subscriber is slow, its queue grows up to ``maxsize`` and overflow events are
dropped (we'd rather drop than block — clients will get the next event).
"""
from __future__ import annotations

import asyncio
import logging
import threading
from typing import Any, Literal

logger = logging.getLogger(__name__)

EventType = Literal[
    "display_changed",
    "display_error",
    "queue_updated",
    "settings_changed",
    "photo_uploaded",
    "photo_deleted",
    "history_changed",
    "system_update",
]


class EventBus:
    def __init__(self, queue_maxsize: int = 32) -> None:
        self._subscribers: dict[asyncio.Queue[dict[str, Any]], asyncio.AbstractEventLoop] = {}
        self._lock = threading.Lock()
        self._maxsize = queue_maxsize

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=self._maxsize)
        loop = asyncio.get_running_loop()
        with self._lock:
            self._subscribers[q] = loop
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        with self._lock:
            self._subscribers.pop(q, None)

    def broadcast(self, event_type: EventType, payload: dict[str, Any] | None = None) -> None:
        event = {"type": event_type, "payload": payload or {}}
        with self._lock:
            subscribers = list(self._subscribers.items())
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None
        for q, loop in subscribers:
            if current_loop is loop:
                self._enqueue(q, event)
            else:
                try:
                    loop.call_soon_threadsafe(self._enqueue, q, event)
                except RuntimeError:  # The subscriber's event loop has shut down.
                    self.unsubscribe(q)

    def _enqueue(self, q: asyncio.Queue[dict[str, Any]], event: dict[str, Any]) -> None:
        """Only touch an asyncio queue on the event loop that owns it."""
        with self._lock:
            if q not in self._subscribers:
                return
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning("Dropped event for a slow subscriber")
