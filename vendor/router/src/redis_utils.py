from __future__ import annotations

import os
import copy
import pathlib
import typing as tp

BASE_DIR = pathlib.Path(__file__).parents[1]

# redis & related imports
import redis.asyncio as redis

# local imports
from . import auth


__all__ = [
    "REDIS_URL",
    "RedisListStructure",
]


auth._ensure_env_loaded()
REDIS_URL: tp.Final = os.getenv("REDIS_URL", None)


class RedisListStructure:
    def __init__(self, url: str = REDIS_URL) -> None:
        assert isinstance(url, str)

        self._url = url

        self.r = redis.Redis.from_url(
            self._url,
            decode_responses=True,
            health_check_interval=30,
            socket_timeout=20,  # seconds
            socket_connect_timeout=5,
            retry_on_timeout=True,
        )

    def __copy__(self) -> "RedisListStructure":
        cls = type(self)
        new = cls.__new__(cls)

        new._url = self._url
        new.r = self.r  # no new tcp connection

        return new

    def __deepcopy__(self, memo: dict[int, tp.Any]) -> "RedisListStructure":
        cls = type(self)
        new = cls.__new__(cls)

        memo[id(self)] = new

        new._url = copy.deepcopy(self._url, memo)
        new.r = self.r

        return new

    async def close(self) -> None:
        await self.r.aclose()

    async def add(self, key: str, value: str) -> int:
        return await self.add_many(key, [value])

    async def add_many(self, key: str, values: list[str]) -> int:
        if not values:
            return await self.count(key)

        return int(await self.r.lpush(key, *values))

    async def pop(self, key: str) -> str | None:
        return await self.r.rpop(key)

    async def peek(self, key: str) -> str | None:
        return await self.r.lindex(key, -1)

    async def count(self, key: str) -> int:
        return int(await self.r.llen(key))

    async def set_ttl(self, key: str, seconds: int) -> bool:
        return bool(await self.r.expire(key, seconds))

    async def clear(self, key: str) -> int:
        return int(await self.r.delete(key))