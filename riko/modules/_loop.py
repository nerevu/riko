# vim: sw=4:ts=4:expandtab
"""
Implements per-item loop execution for embedded modules.

Each source item is processed independently by the embedded module, and its
results are emitted or assigned back to that same parent item.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterable, Generator
from functools import partial
from typing import TYPE_CHECKING, cast

import pygogo as gogo

from riko.bado._util import maybe_deferred
from riko.bado.itertools import as_async
from riko.types._guards import is_subpipe

from ._assignment import get_subpipe

if TYPE_CHECKING:
    from logging import Logger

    from riko.runtime.context import Context
    from riko.types._compiler import CountValues, EmbedKwargs
    from riko.types._streams import AsyncItems, AsyncStream, Feed, Item, Items, Stream
    from riko.types._wrappers import (
        AsyncProcessorWrapper,
        AsyncSubPipe,
        SyncProcessorWrapper,
        SyncSubPipe,
    )

logger: Logger = gogo.Gogo(__name__, monolog=True).logger


def _take_first(results: Items) -> Stream:
    """
    Emits only the first result, then promptly closes the underlying iterator.

    ``count="first"`` is already lazy (the loop stops pulling after one), but a
    child generator holding resources would otherwise linger until GC; closing it
    releases those resources as soon as the loop moves to the next parent.
    """
    iterator = iter(results)

    try:
        for item in iterator:
            yield item
            break
    finally:
        if isinstance(iterator, Generator):
            iterator.close()


async def _atake_first(results: AsyncItems) -> AsyncStream:
    iterator = aiter(results)

    try:
        async for item in iterator:
            yield item
            break
    finally:
        if isinstance(iterator, AsyncGenerator):
            await iterator.aclose()


def _take[T: Feed](results: T, count: CountValues | None = "all") -> T:
    if count != "first":
        result = results
    elif isinstance(results, AsyncIterable):
        result = _atake_first(results)
    else:
        result = _take_first(results)

    return result


def _fold_parent(  # noqa: E302
    parent: Item, results: Stream, assign: str, emit: bool = False
) -> Stream:
    """
    Fold a parent's per-child ``results`` back against that parent.

    ``emit`` True yields each child result verbatim (replacing the parent);
    ``emit`` False yields a preserved parent copy per result with the result
    stored under ``assign``. Empty-child rule: when the child yields nothing, an
    ``emit=False`` loop still yields the untouched parent (assign-mode preserves
    the record) while an ``emit=True`` loop drops it (emit-mode has nothing to
    emit). ``assign`` is guaranteed non-empty in ``emit=False`` mode: the module
    decorator (``Module.prepare``) resolves an unset ``assign`` to the module
    name (or ``"content"`` for sources) before the loop ever runs.
    """
    yielded = False

    for value in results:
        yielded = True
        yield value if emit else cast("Item", {**parent, assign: value})

    if not (yielded or emit):
        yield parent


async def _afold_parent(  # noqa: E302
    parent: Item, results: Stream | AsyncStream, assign: str, emit: bool = False
) -> AsyncStream:
    yielded = False

    async for value in as_async(results):
        yielded = True
        yield value if emit else cast("Item", {**parent, assign: value})

    if not (yielded or emit):
        yield parent


def _run_loop_sync(
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
    embedder = get_subpipe(embed, context, embedded_kwargs, field=field)

    for parent in source:
        stream = _take(embedder(parent), count)
        yield from _fold_parent(parent, stream, assign, emit)


async def _run_loop_async(
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
    embedder = get_subpipe(embed, context, embedded_kwargs, field=field)

    async for parent in as_async(source):
        items = await maybe_deferred(embedder, parent)
        stream = _take(items, count)

        async for value in _afold_parent(parent, stream, assign, emit):
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
    embed_type = embed.type if embed else None
    handled = True
    looped = False
    stream = source
    loop = partial(_run_loop_sync, field=field, assign=assign, emit=emit, count=count)

    if embed is None:
        handled = False
    elif is_subpipe(embed):
        # A sub-pipeline embed is self-contained, so it runs per parent with no
        # embedded kwargs (its own modules carry their conf).
        stream = loop(embed, None, context, source)
        looped = True
    elif embed_type and embed.loopable:
        stream = loop(embed, embedded_kwargs, context, source)
        looped = True
    elif embed_type:
        logger.error(f"{embed.name} is not loopable and can't be embedded.")
    elif callable(embed):
        logger.error("Custom embedded pipes are not currently supported.")
    elif module_name == "loop":
        logger.error("No embedded pipe provided!")
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
    embed_type = embed.type if embed else None
    handled = True
    looped = False
    stream = source
    loop = partial(_run_loop_async, field=field, assign=assign, emit=emit, count=count)

    if embed is None:
        handled = False
    elif is_subpipe(embed):
        # A sub-pipeline embed is self-contained, so it runs per parent with no
        # embedded kwargs (its own modules carry their conf).
        stream = loop(embed, None, context, source)
        looped = True
    elif embed_type and embed.loopable:
        stream = loop(embed, embedded_kwargs, context, source)
        looped = True
    elif embed_type:
        logger.error(f"{embed.name} is not loopable and can't be embedded.")
    elif callable(embed):
        logger.error("Custom embedded pipes are not currently supported.")
    elif op_module_name == "loop":
        logger.error("No embedded pipe provided!")
    else:
        handled = False

    return handled, looped, stream
