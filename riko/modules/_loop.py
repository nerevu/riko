# vim: sw=4:ts=4:expandtab
"""
Implements per-item loop execution for embedded modules.

Each input item is processed independently by the embedded module, and its
results are emitted or assigned back to that same parent item.
"""

from __future__ import annotations

from collections.abc import AsyncIterable
from functools import partial
from typing import TYPE_CHECKING, cast

from riko.bado._util import maybe_aclosing, maybe_async, maybe_closing
from riko.bado.itertools import as_async
from riko.base._logging import get_logger
from riko.types._wrappers import is_subpipe

from ._assignment import bind_subpipe

if TYPE_CHECKING:
    from logging import Logger

    from riko.definitions._context import Context
    from riko.types._pipedef import CountValues, EmbedKwargs
    from riko.types._streams import AsyncItems, AsyncStream, Feed, Item, Items, Stream
    from riko.types._wrappers import (
        AsyncProcessorWrapper,
        AsyncSubPipe,
        SyncProcessorWrapper,
        SyncSubPipe,
    )

logger: Logger = get_logger(__name__)


def _take_first(results: Items) -> Stream:
    """
    Emits only the first result, then promptly closes the underlying iterator.

    ``count="first"`` is already lazy (the loop stops pulling after one), but a
    child generator holding resources would otherwise linger until GC; closing it
    releases those resources as soon as the loop moves to the next parent.
    """
    with maybe_closing(iter(results)) as stream:
        for item in stream:
            yield item
            break


async def _atake_first(results: AsyncItems) -> AsyncStream:
    async with maybe_aclosing(aiter(results)) as iterator:
        async for item in iterator:
            yield item
            break


def _take[T: Feed](results: T, count: CountValues | None = "all") -> T:
    if count != "first":
        result = results
    elif isinstance(results, AsyncIterable):
        result = _atake_first(results)
    else:
        result = _take_first(results)

    return result


def _fold_parent(
    parent: Item, results: Stream, assign: str, emit: bool = False
) -> Stream:
    """
    Folds a parent's child results back against that parent.

    If a child yields nothing, this still yields the untouched parent unless ``emit`` is
    set. ``results`` closes once the fold is done with it, whether drained or closed
    early.

    Args:

        parent: The item the child ran for.
        results: The child's results for ``parent``.

        assign: The key each result is stored under when ``emit`` is not set. Never
            empty, since an unset ``assign`` resolves to the module name first.

    Kwargs:

        emit: Yields each result in place of the parent instead of a parent copy.

    """
    yielded = False

    with maybe_closing(iter(results)) as stream:
        for value in stream:
            yielded = True
            yield value if emit else cast("Item", {**parent, assign: value})

    if not (yielded or emit):
        yield parent


async def _afold_parent(
    parent: Item, results: Stream | AsyncStream, assign: str, emit: bool = False
) -> AsyncStream:
    yielded = False

    async with maybe_aclosing(as_async(results)) as iterator:
        async for value in iterator:
            yielded = True
            yield value if emit else cast("Item", {**parent, assign: value})

    if not (yielded or emit):
        yield parent


def _run_loop(
    embed: SyncProcessorWrapper | SyncSubPipe,
    embedded_kwargs: EmbedKwargs | None,
    context: Context,
    source: Items,
    *,
    field: str | None,
    assign: str,
    emit: bool,
    count: CountValues | None,
) -> Stream:
    embedder = bind_subpipe(embed, context, embedded_kwargs, field=field)

    for parent in source:
        taken = _take(embedder(parent), count)
        yield from _fold_parent(parent, taken, assign, emit)


async def _arun_loop(
    embed: AsyncProcessorWrapper | AsyncSubPipe,
    embedded_kwargs: EmbedKwargs | None,
    context: Context,
    source: Feed,
    *,
    field: str | None,
    assign: str,
    emit: bool,
    count: CountValues | None,
) -> AsyncStream:
    args = embed, context, embedded_kwargs
    embedder = bind_subpipe(*args, field=field, host_is_async=True)

    async for parent in as_async(source):
        items = await maybe_async(embedder, parent)
        taken = _take(items, count)
        stream = _afold_parent(parent, taken, assign, emit)

        async with maybe_aclosing(stream) as folded:
            async for value in folded:
                yield value


def loop_embed_sync(
    embed: SyncProcessorWrapper | SyncSubPipe | None,
    embedded_kwargs: EmbedKwargs | None,
    context: Context,
    source: Stream,
    module_name: str,
    *,
    field: str | None = None,
    assign: str,
    emit: bool,
    count: CountValues | None = None,
) -> tuple[bool, bool, Stream]:
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
    loop = partial(_run_loop, field=field, assign=assign, emit=emit, count=count)

    if embed is None:
        handled = False
    elif is_subpipe(embed):
        # A stored workflow is self-contained, so it runs per parent without the
        # loop's embed kwargs (its own nodes carry their conf).
        stream = loop(embed, None, context, source)
        looped = True
    elif embed_type and embed.loopable:
        stream = loop(embed, embedded_kwargs, context, source)
        looped = True
    elif embed_type:
        logger.error(f"{embed.name} is not loopable and can't be embedded.")
    elif callable(embed):
        logger.error("Custom embedded modules are not currently supported.")
    elif module_name == "loop":
        logger.error("No embedded module provided!")
    else:
        handled = False

    return handled, looped, stream


def loop_embed_async(
    embed: AsyncProcessorWrapper | AsyncSubPipe | None,
    embedded_kwargs: EmbedKwargs | None,
    context: Context,
    source: Feed,
    op_module_name: str,
    *,
    field: str | None = None,
    assign: str,
    emit: bool,
    count: CountValues | None = None,
) -> tuple[bool, bool, Feed]:
    """
    Build the lazy async counterpart to ``loop_embed_sync``.

    It returns a sequential per-parent async generator without advancing the source.
    It does not materialize the source or run embeds concurrently, so ordering,
    backpressure, and early exit on ``count="first"`` follow from sequential
    iteration.
    """
    embed_type = getattr(embed, "type", None)
    handled = True
    looped = False
    stream = source
    loop = partial(_arun_loop, field=field, assign=assign, emit=emit, count=count)

    if embed is None:
        handled = False
    elif is_subpipe(embed):
        # A stored workflow is self-contained, so it runs per parent without the
        # loop's embed kwargs (its own nodes carry their conf).
        stream = loop(embed, None, context, source)
        looped = True
    elif embed_type and embed.loopable:
        stream = loop(embed, embedded_kwargs, context, source)
        looped = True
    elif embed_type:
        logger.error(f"{embed.name} is not loopable and can't be embedded.")
    elif callable(embed):
        logger.error("Custom embedded modules are not currently supported.")
    elif op_module_name == "loop":
        logger.error("No embedded module provided!")
    else:
        handled = False

    return handled, looped, stream
