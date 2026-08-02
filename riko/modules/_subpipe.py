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

from collections.abc import Callable
from typing import cast

from riko.types.general import ProcessorWrapperOutput, SubPipe
from riko.types.modules import ModuleSubtype

SUBPIPE_TYPE = "pipe"


def mark_subpipe(
    pipe: Callable[..., ProcessorWrapperOutput | list[str] | list[tuple[str, ...]]],
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
    return cast(SubPipe, pipe)


def is_subpipe(pipe: object) -> bool:
    return callable(pipe) and getattr(pipe, "type", None) == SUBPIPE_TYPE
