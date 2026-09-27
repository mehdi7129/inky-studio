"""WebSocket endpoint that fans out events from the in-process EventBus."""
from __future__ import annotations

import asyncio
import logging

import anyio
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
    sessions = None if auth.auth_disabled() else websocket.app.state.sessions
    revoked = sessions.watch_revocation() if sessions is not None else None
    close_lock = asyncio.Lock()
    closed = False

    async def close_unauthorized() -> None:
        nonlocal closed
        async with close_lock:
            if not closed:
                closed = True
                await websocket.close(code=1008)

    async def watch_revocation() -> None:
        assert revoked is not None
        while True:
            # Check before waiting too, to cover revocation while accepting.
            if not authenticated():
                await close_unauthorized()
                return
            await revoked.wait()
            revoked.clear()

    async def send_events() -> None:
        while True:
            event = await event_queue.get()
            if not authenticated():
                await close_unauthorized()
                return
            await websocket.send_json(event)

    async def receive_disconnect() -> None:
        while True:
            if not authenticated():
                await close_unauthorized()
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
        if revoked is not None:
            tasks.append(asyncio.create_task(watch_revocation()))
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
        # Unsubscribe before awaiting task cleanup: a second cancellation can
        # interrupt gather, but must never leave this connection on the bus.
        bus.unsubscribe(event_queue)
        if sessions is not None and revoked is not None:
            sessions.unwatch_revocation(revoked)
        for task in tasks:
            task.cancel()
        # Preserve the enclosing ASGI cancellation scope while draining tasks.
        # Otherwise gather can replace its cancellation with a bare child
        # CancelledError that the enclosing scope cannot recognize.
        with anyio.CancelScope(shield=True):
            await asyncio.gather(*tasks, return_exceptions=True)
