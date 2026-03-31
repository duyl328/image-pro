import asyncio
import json
from collections import defaultdict
from typing import Optional

from fastapi import WebSocket

# Global registry: task_id -> set of websockets
_connections: dict[int, set[WebSocket]] = defaultdict(set)
_lock = asyncio.Lock()


async def connect(task_id: int, ws: WebSocket):
    await ws.accept()
    async with _lock:
        _connections[task_id].add(ws)


async def disconnect(task_id: int, ws: WebSocket):
    async with _lock:
        _connections[task_id].discard(ws)
        if not _connections[task_id]:
            del _connections[task_id]


async def broadcast(task_id: int, event: str, data: Optional[dict] = None):
    """Send a progress event to all WebSocket clients watching a task."""
    message = json.dumps({"event": event, "data": data or {}})
    async with _lock:
        dead = []
        for ws in _connections.get(task_id, set()):
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            _connections[task_id].discard(ws)
