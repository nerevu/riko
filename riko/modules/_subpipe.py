# vim: sw=4:ts=4:expandtab
"""
riko.modules._subpipe
~~~~~~~~~~~~~~~~~~~~~~
Declared metadata for compiled sub-pipelines (``pipe_*`` callables). A
sub-pipeline never passes through the ``@processor``/``@operator`` decorators, so
it carries none of the inferred module metadata. Its contract is *known* by
construction — it takes ``(item, context)``, returns a stream, and any pipe is
loopable — so the metadata is **declared** here rather than inferred.
"""

from collections.abc import Awaitable, Callable
from typing import Literal, cast, overload

from riko.types.general import (
    AsyncSubPipe,
    ProcessorWrapperOutput,
    SubPipe,
    SyncSubPipe,
)
from riko.types.modules import ModuleSubtype

SUBPIPE_TYPE = "pipe"

type _SubPipeOutput = ProcessorWrapperOutput | list[str] | list[tuple[str, ...]]
type _SyncSubPipeFunc = Callable[..., _SubPipeOutput]
type _AsyncSubPipeFunc = Callable[..., Awaitable[_SubPipeOutput]]


@overload
def mark_subpipe(  # noqa: E704
    pipe: _SyncSubPipeFunc,
    *,
    subtype: ModuleSubtype = ...,
    loopable: bool = ...,
    is_async: Literal[False] = ...,
) -> SyncSubPipe: ...
@overload  # noqa: E302
def mark_subpipe(  # noqa: E704
    pipe: _AsyncSubPipeFunc,
    *,
    subtype: ModuleSubtype = ...,
    loopable: bool = ...,
    is_async: Literal[True],
) -> AsyncSubPipe: ...
def mark_subpipe(  # noqa: E302
    pipe: _SyncSubPipeFunc | _AsyncSubPipeFunc,
    *,
    subtype: ModuleSubtype = "transformer",
    loopable: bool = True,
    is_async: bool = False,
) -> SubPipe:
    setattr(pipe, "name", getattr(pipe, "__name__", SUBPIPE_TYPE))  # noqa: B010
    setattr(pipe, "type", SUBPIPE_TYPE)  # noqa: B010
    setattr(pipe, "subtype", subtype)  # noqa: B010
    setattr(pipe, "subtypes", {subtype})  # noqa: B010
    setattr(pipe, "loopable", loopable)  # noqa: B010
    setattr(pipe, "pollable", False)  # noqa: B010
    return cast(AsyncSubPipe, pipe) if is_async else cast(SyncSubPipe, pipe)


def is_subpipe(pipe: object) -> bool:
    return callable(pipe) and getattr(pipe, "type", None) == SUBPIPE_TYPE
