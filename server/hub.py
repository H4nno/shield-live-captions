"""WebSocket broadcast hub with a small replay cache for late joiners."""
from __future__ import annotations

import asyncio
from collections import deque


class Hub:
    def __init__(self, replay: int = 5):
        self._clients: set[asyncio.Queue] = set()
        self._recent: deque[dict] = deque(maxlen=replay)

    @property
    def client_count(self) -> int:
        return len(self._clients)

    async def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._clients.add(q)
        for event in self._recent:
            q.put_nowait(event)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        self._clients.discard(q)

    def publish(self, event: dict):
        """Must be called on the loop thread. Keeps only finals in the replay cache."""
        if event.get("type") == "final":
            self._recent.append(event)
        for q in list(self._clients):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                try:
                    q.get_nowait()
                    q.put_nowait(event)
                except Exception:
                    pass
