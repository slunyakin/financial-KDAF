"""Redis connector — query-result cache and KG context cache.

Used by:
  - Supervisor: build_cache_key → get/setex for query-result cache
  - execution/cypher.py: kg_cache_key → get/setex for KG context cache
  - Cache invalidation path: scan_match + delete on role change or KG writes
"""
from __future__ import annotations

from typing import List, Optional

import redis.asyncio as aioredis


class RedisConnector:
    def __init__(self, url: str = "redis://localhost:6379") -> None:
        self._client: aioredis.Redis = aioredis.from_url(url, decode_responses=True)

    async def get(self, key: str) -> Optional[str]:
        return await self._client.get(key)

    async def setex(self, key: str, ttl: int, value: str) -> None:
        await self._client.setex(key, ttl, value)

    async def delete(self, *keys: str) -> None:
        if keys:
            await self._client.delete(*keys)

    async def scan_match(self, pattern: str) -> List[str]:
        """Return all keys matching pattern (uses SCAN — safe on large keyspaces)."""
        keys: List[str] = []
        async for key in self._client.scan_iter(pattern):
            keys.append(key)
        return keys

    async def close(self) -> None:
        await self._client.aclose()
