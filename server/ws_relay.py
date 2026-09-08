"""Fan-out from the Live Data Service to connected browser clients. The
frontend only ever opens a connection to THIS endpoint -- never to Kite's
WebSocket directly, and never with Kite credentials anywhere near it."""
from __future__ import annotations
from collections import defaultdict
import logging

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger("ws_relay")

_connections: dict[str, set[WebSocket]] = defaultdict(set)


async def connect(symbol: str, ws: WebSocket):
    """Accept a WebSocket connection for a symbol and maintain it."""
    await ws.accept()
    _connections[symbol].add(ws)
    logger.info(f"Client connected to {symbol} ({len(_connections[symbol])} total)")
    try:
        while True:
            # Frontend doesn't need to send anything -- this just keeps
            # the connection alive and detects disconnects.
            await ws.receive_text()
    except WebSocketDisconnect:
        _connections[symbol].discard(ws)
        logger.info(f"Client disconnected from {symbol} ({len(_connections[symbol])} remaining)")


async def broadcast(symbol: str, message: dict):
    """Send a message to all clients subscribed to this symbol."""
    dead = []
    for ws in _connections.get(symbol, ()):
        try:
            await ws.send_json(message)
        except Exception as e:
            logger.debug(f"Failed to send to {symbol}: {e}")
            dead.append(ws)
    for ws in dead:
        _connections[symbol].discard(ws)


def get_connection_count(symbol: str) -> int:
    """Return the number of active connections for a symbol."""
    return len(_connections.get(symbol, set()))


def get_all_symbols() -> list[str]:
    """Return all symbols with active connections."""
    return [s for s in _connections if _connections[s]]
