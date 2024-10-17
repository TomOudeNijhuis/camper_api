import time
from asyncio import Lock
from dataclasses import dataclass
from typing import Dict, Optional, ClassVar
from datetime import datetime


@dataclass
class Value:
    data_str: str
    created: datetime
    ttl_ts: int


class InMemoryBackend:
    _store: Dict[str, Value] = {}
    _lock = Lock()

    @property
    def _now(self) -> int:
        return int(time.time())

    def _get(self, key: str) -> Optional[Value]:
        v = self._store.get(key)
        if v:
            if v.ttl_ts < self._now:
                del self._store[key]
            else:
                return v
        return None

    async def get(self, key: str):
        async with self._lock:
            v = self._get(key)
            if v:
                return v.data_str, v.created

            return None, None

    async def set(
        self, key: str, data_str: str, created: datetime, expire: Optional[int] = None
    ) -> None:
        async with self._lock:
            self._store[key] = Value(data_str, created, self._now + (expire or 0))

    async def clear(self, key: Optional[str] = None) -> int:
        count = 0
        del self._store[key]
        count += 1

        return count


class MemoryCache:
    _backend: ClassVar[InMemoryBackend] = None
    _init: ClassVar[bool] = False

    @classmethod
    def init(
        cls,
    ) -> None:
        if cls._init:
            return
        cls._init = True
        cls._backend = InMemoryBackend()

    @classmethod
    def reset(cls) -> None:
        cls._init = False

    @classmethod
    def get_backend(cls) -> InMemoryBackend:
        assert cls._backend, "You must call init first!"  # noqa: S101
        return cls._backend

    @classmethod
    async def clear(cls, key: Optional[str] = None) -> int:
        assert cls._backend is not None, "You must call init first!"  # noqa: S101
        return await cls._backend.clear(key)
