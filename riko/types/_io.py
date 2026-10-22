"""Path and closeable I/O typing contracts and their guards."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from typing_extensions import TypeIs

from ._guards import isinstance_strict

type PathLike = str | Path


@runtime_checkable
class SyncCloseable(Protocol):
    def close(self) -> object | None: ...  # noqa: E704


@runtime_checkable
class AsyncCloseable(Protocol):
    async def aclose(self) -> object | None: ...  # noqa: E704


type Closeable = SyncCloseable | AsyncCloseable

CloseableType = (SyncCloseable, AsyncCloseable)
PathLikeType: tuple[type[str], type[Path]] = (str, Path)


def is_sync_closeable(val: object) -> TypeIs[SyncCloseable]:
    return isinstance_strict(val, SyncCloseable)


def is_async_closeable(val: object) -> TypeIs[AsyncCloseable]:
    return isinstance_strict(val, AsyncCloseable)


def is_closeable(val: object) -> TypeIs[Closeable]:
    return is_sync_closeable(val) or is_async_closeable(val)
