# vim: sw=4:ts=4:expandtab
"""
riko.modules._loop
~~~~~~~~~~~~~~~~~~
Loop-specific execution, extracted from the generic operator decorator. Owns
embedded-target validation, child-context creation (via ``_get_subpipe``), and
the per-parent fold of an embedded processor over the source stream.

The loop runs the embed once per parent and folds its results back against *that
parent* — ``count`` reduces per parent, ``emit`` yields the child results, and
``assign`` stores each result on a preserved copy of the parent (one copy per
result). This is the Yahoo per-parent contract, shared by ``loop_embed_sync`` and
``loop_embed_async`` (``loop.async_pipe``) via the common ``_fold_parent``/
``_take`` fold. See docs/gameplans/loop-restructure.md.

The lazy-async loop runs the embed once per parent *sequentially* and yields the
per-parent fold incrementally as an ``AsyncIterator`` — preserving parent order,
applying backpressure (the source only advances as the consumer pulls), and
letting ``count="first"`` stop after the first result without materializing the
rest.
"""

from functools import partial
from itertools import islice
from logging import Logger
from typing import Literal, cast, overload

import pygogo as gogo

from riko.bado.itertools import async_iter
from riko.context import Context
from riko.modules._assignment import get_subpipe
from riko.modules._subpipe import is_subpipe
from riko.types.compile import EmbedKwargs
from riko.types.general import (
    AsyncProcessorWrapper,
    AsyncStreamOrValueStream,
    AsyncSubPipe,
    Item,
    Items,
    ItemsOrValues,
    Stream,
    StreamOrValueStream,
    SyncProcessorWrapper,
    SyncSubPipe,
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
    embed: SyncProcessorWrapper | SyncSubPipe,
    embedded_kwargs: EmbedKwargs | None,
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
        items = _take(embedder(parent), count)
        yield from _fold_parent(parent, items, assign or "", bool(emit))


async def _run_loop_async(
    embed: AsyncProcessorWrapper | AsyncSubPipe,
    embedded_kwargs: EmbedKwargs | None,
    context: Context,
    source: Stream,
    *,
    field: str | None,
    assign: str | None = None,
    emit: bool | None = None,
    count: CountValues | None,
) -> AsyncStreamOrValueStream:
    embedder = get_subpipe(embed, context, embedded_kwargs, field=field)

    async for parent in async_iter(source):
        results = _take(await embedder(parent), count)

        for value in _fold_parent(parent, results, assign or "", bool(emit)):
            yield value


def loop_embed_sync(
    embed: SyncProcessorWrapper | SyncSubPipe | None,
    embedded_kwargs: EmbedKwargs | None,
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
    loop = partial(_run_loop_sync, field=field, assign=assign, emit=emit, count=count)

    if is_subpipe(embed):
        # A sub-pipeline embed is self-contained, so it runs per parent with no
        # embedded kwargs (its own modules carry their conf).
        stream = loop(cast(SyncSubPipe, embed), None, context, source)
        looped = True
    elif embed and embed_type and embed.loopable:
        stream = loop(embed, embedded_kwargs, context, source)
        looped = True
    elif embed_type:
        logger.error(f"{embed.name} is not loopable and can't be embedded.")
    elif embed and callable(embed):
        logger.error("Custom embedded pipes are not currently supported.")
    elif op_module_name == "loop":
        logger.error("No embedded pipe provided!")
    else:
        handled = False

    return handled, looped, stream


def loop_embed_async(
    embed: AsyncProcessorWrapper | AsyncSubPipe | None,
    embedded_kwargs: EmbedKwargs | None,
    context: Context,
    source: Stream,
    op_module_name: str,
    *,
    field: str | None = None,
    assign: str | None = None,
    emit: bool | None = None,
    count: CountValues | None = None,
) -> tuple[bool, bool, AsyncStreamOrValueStream | Stream]:
    """
    Lazy-async counterpart of ``loop_embed_sync``: constructs (without advancing)
    a sequential per-parent async loop generator that yields results as the
    consumer pulls. Unlike the eager path this neither materializes the source
    nor runs the embeds concurrently — ordering, backpressure, and early exit on
    ``count="first"`` fall out of sequential iteration.
    """
    embed_type = getattr(embed, "type", None)
    handled = True
    looped = False
    stream = source
    loop = partial(_run_loop_async, field=field, assign=assign, emit=emit, count=count)

    if is_subpipe(embed):
        # A sub-pipeline embed is self-contained, so it runs per parent with no
        # embedded kwargs (its own modules carry their conf).
        stream = loop(cast(AsyncSubPipe, embed), None, context, source)
        looped = True
    elif embed and embed_type and embed.loopable:
        stream = loop(embed, embedded_kwargs, context, source)
        looped = True
    elif embed_type:
        logger.error(f"{embed.name} is not loopable and can't be embedded.")
    elif embed and callable(embed):
        logger.error("Custom embedded pipes are not currently supported.")
    elif op_module_name == "loop":
        logger.error("No embedded pipe provided!")
    else:
        handled = False

    return handled, looped, stream
