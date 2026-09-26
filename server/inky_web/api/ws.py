"""WebSocket endpoint that fans out events from the in-process EventBus."""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from inky_web import auth

router = APIRouter(tags=["ws"])
logger = logging.getLogger(__name__)


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    token = websocket.cookies.get(auth.COOKIE_NAME)

    def authenticated() -> bool:
        return auth.auth_disabled() or websocket.app.state.sessions.validate(token)

    if not authenticated():
        await websocket.close(code=1008)
        return

    bus = websocket.app.state.bus
    await websocket.accept()
    event_queue = bus.subscribe()
    tasks: list[asyncio.Task] = []

    async def send_events() -> None:
        while True:
            event = await event_queue.get()
            if not authenticated():
                await websocket.close(code=1008)
                return
            await websocket.send_json(event)

    async def receive_disconnect() -> None:
        while True:
            if not authenticated():
                await websocket.close(code=1008)
                return
            try:
                message = await asyncio.wait_for(websocket.receive(), timeout=30)
            except TimeoutError:
                continue
            if message["type"] == "websocket.disconnect":
                return

    try:
        await websocket.send_json({"type": "hello", "payload": {}})
        tasks = [asyncio.create_task(send_events()), asyncio.create_task(receive_disconnect())]
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    except WebSocketDisconnect:
        logger.debug("WebSocket client disconnected")
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001
        logger.exception("WebSocket loop crashed")
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        bus.unsubscribe(event_queue)
