"""WebSocket endpoint that fans out events from the in-process EventBus."""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter(tags=["ws"])
logger = logging.getLogger(__name__)


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    bus = websocket.app.state.bus
    event_queue = bus.subscribe()
    await websocket.accept()
    try:
        await websocket.send_json({"type": "hello", "payload": {}})
        while True:
            event = await event_queue.get()
            await websocket.send_json(event)
    except WebSocketDisconnect:
        logger.debug("WebSocket client disconnected")
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001
        logger.exception("WebSocket loop crashed")
    finally:
        bus.unsubscribe(event_queue)
