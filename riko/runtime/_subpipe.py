# vim: sw=4:ts=4:expandtab
"""Metadata helpers for compiled sub-pipeline callables."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast, overload

from riko.base._config import SUBPIPE_TYPE

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from riko.types._wrappers import AsyncSubPipe, SubPipe, SyncSubPipe
    from riko.types.modules import ModuleSubtype


@overload
def mark_subpipe(  # noqa: E704  # pyright: ignore[reportOverlappingOverload]
    pipe: Callable[..., Awaitable[object]],
    *,
    subtype: ModuleSubtype = ...,
    loopable: bool = ...,
) -> AsyncSubPipe: ...
@overload  # noqa: E302
def mark_subpipe(  # noqa: E704
    pipe: Callable[..., object], *, subtype: ModuleSubtype = ..., loopable: bool = ...
) -> SyncSubPipe: ...
def mark_subpipe(  # noqa: E302
    pipe: Callable[..., object],
    *,
    subtype: ModuleSubtype = "transformer",
    loopable: bool = True,
) -> SubPipe:
    setattr(pipe, "name", getattr(pipe, "__name__", SUBPIPE_TYPE))  # noqa: B010
    setattr(pipe, "type", SUBPIPE_TYPE)  # noqa: B010
    setattr(pipe, "subtype", subtype)  # noqa: B010
    setattr(pipe, "subtypes", {subtype})  # noqa: B010
    setattr(pipe, "loopable", loopable)  # noqa: B010
    setattr(pipe, "pollable", False)  # noqa: B010
    return cast("SubPipe", pipe)
