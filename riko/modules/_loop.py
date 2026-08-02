# vim: sw=4:ts=4:expandtab
"""
riko.modules._loop
~~~~~~~~~~~~~~~~~~
Loop-specific execution, extracted from the generic operator decorator. Owns
embedded-target validation, child-context creation (via ``_get_subpipe``), and
the per-parent fold of an embedded processor over the source stream.

Phase 2 (sync): the loop runs the embed once per parent and folds its results
back against *that parent* — ``count`` reduces per parent, ``emit`` yields the
child results, and ``assign`` stores each result on a preserved copy of the
parent (one copy per result). This is the Yahoo per-parent contract. Loop-level
``field`` selection and the async per-parent fold arrive in later Phase 2 commits
(see docs/gameplans/loop-restructure.md); the async path here is still the eager
flatten (unreached — the loop module is sync-only until its ``async_pipe`` lands).
"""

from itertools import chain, islice
from logging import Logger
from typing import Literal, cast, overload

import pygogo as gogo

from riko.bado.itertools import async_map
from riko.context import Context
from riko.modules._assignment import get_subpipe
from riko.types.compile import PipeModule
from riko.types.general import (
    AsyncProcessorWrapper,
    Item,
    Items,
    ItemsOrValues,
    Stream,
    StreamOrValueStream,
    SyncProcessorWrapper,
)
from riko.types.modules import CountValues

logger: Logger = gogo.Gogo(__name__, monolog=True).logger


def _take(results: ItemsOrValues, count: CountValues | None = "all") -> ItemsOrValues:
    return islice(results, 1) if count == "first" else results


@overload
def _fold_parent(  # noqa: E704
    parent: Item, results: ItemsOrValues, assign: str, emit: Literal[False]
) -> Stream: ...
@overload  # noqa: E302
def _fold_parent(  # noqa: E704
    parent: Item, results: Items, assign: str, emit: bool
) -> Stream: ...
@overload  # noqa: E302
def _fold_parent(  # noqa: E704
    parent: Item, results: ItemsOrValues, assign: str, emit: bool
) -> StreamOrValueStream: ...
def _fold_parent(  # noqa: E302
    parent: Item, results: ItemsOrValues, assign: str, emit: bool
) -> StreamOrValueStream:
    yielded = False

    for value in results:
        yielded = True
        yield value if emit else cast(Item, {**parent, assign: value})

    if not (yielded or emit):
        yield parent


def _run_loop_sync(
    embed: SyncProcessorWrapper,
    embedded_kwargs: PipeModule | None,
    context: Context,
    source: Stream,
    *,
    field: str | None,
    assign: str | None = None,
    emit: bool | None = None,
    count: CountValues | None,
) -> StreamOrValueStream:
    embedder = get_subpipe(embed, context, embedded_kwargs, field=field)

    for parent in source:
        results = _take(embedder(parent), count)
        yield from _fold_parent(parent, results, assign or "", bool(emit))


def loop_embed_sync(
    embed: SyncProcessorWrapper | None,
    embedded_kwargs: PipeModule | None,
    context: Context,
    source: Stream,
    op_module_name: str,
    *,
    field: str | None = None,
    assign: str | None = None,
    emit: bool | None = None,
    count: CountValues | None = None,
) -> tuple[bool, bool, StreamOrValueStream]:
    """
    Resolve the sync embedded stream for an operator invocation.

    Returns ``(handled, looped, stream)``. A loopable embed runs per-parent and
    returns the final stream (``looped`` True means the caller must not process the
    item again); an embed that is present but cannot run is logged and passes ``source``
    through (``looped`` False); no embed at all sets ``handled`` False so the
    caller runs the operator parser instead.
    """
    embed_type = getattr(embed, "type", None)
    handled = True
    looped = False
    stream = source

    if embed and embed_type and embed.loopable:
        stream = _run_loop_sync(
            embed,
            embedded_kwargs,
            context,
            source,
            field=field,
            assign=assign,
            emit=emit,
            count=count,
        )
        looped = True
    elif embed_type:
        logger.error(f"{embed.name} is not loopable and can't be embedded.")
    elif embed and callable(embed):
        if name := getattr(embed, "__name__", None):
            logger.error(f"{name} is a custom pipe and can't be embedded.")
        else:
            logger.error("Custom embedded pipes are not currently supported.")
    elif op_module_name == "loop":
        logger.error("No embedded pipe provided!")
    else:
        handled = False

    return handled, looped, stream


async def loop_embed_async_eager(
    embed: AsyncProcessorWrapper | None,
    embedded_kwargs: PipeModule | None,
    context: Context,
    source: Stream,
    op_module_name: str,
) -> tuple[bool, bool, StreamOrValueStream]:
    """
    Eager-async counterpart of ``loop_embed_sync``. The per-parent async loop and
    the ``async_pipe`` loop land in a later Phase 2 commit; today this keeps the
    eager flatten (``looped`` False) and is unreached (the loop module is
    sync-only). See the module docstring for the trajectory.
    """
    embed_type = getattr(embed, "type", None)
    handled = True
    looped = False
    stream = source

    if embed and embed_type and embed.loopable:
        embedder = get_subpipe(embed, context, embedded_kwargs)
        stream_map = await async_map(embedder, source)
        stream = chain.from_iterable(stream_map)
    elif embed_type:
        logger.error(f"{embed.name} is not loopable and can't be embedded.")
    elif embed and callable(embed):
        if name := getattr(embed, "__name__", None):
            logger.error(f"{name} is a custom pipe and can't be embedded.")
        else:
            logger.error("Custom embedded pipes are not currently supported.")
    elif op_module_name == "loop":
        logger.error("No embedded pipe provided!")
    else:
        handled = False

    return handled, looped, stream
