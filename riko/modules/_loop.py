# vim: sw=4:ts=4:expandtab
"""
riko.modules._loop
~~~~~~~~~~~~~~~~~~
Loop-specific execution, extracted from the generic operator decorator. Owns
embedded-target validation, child-context creation (via ``_get_subpipe``), and
the map-and-flatten of an embedded processor over the source stream.

Phase 1: this reproduces the *current* pre-Yahoo behavior exactly (map the embed
over each source item, then globally flatten the per-item child streams). The
per-parent fold, loop-level ``field``, and parent-preserving ``assign`` arrive in
Phase 2 (see docs/gameplans/loop-restructure.md).
"""

from itertools import chain
from logging import Logger

import pygogo as gogo

from riko.bado.itertools import async_map
from riko.context import Context
from riko.modules._assignment import get_subpipe
from riko.types.general import (
    AsyncProcessorWrapper,
    Stream,
    StreamOrValueStream,
    SyncProcessorWrapper,
)

logger: Logger = gogo.Gogo(__name__, monolog=True).logger


def loop_embed_sync(
    embed: SyncProcessorWrapper | None,
    embedded_kwargs: dict,
    context: Context,
    source: Stream,
    op_module_name: str,
) -> tuple[bool, StreamOrValueStream]:
    """
    Resolve the sync embedded stream for an operator invocation.

    Returns ``(handled, stream)``. ``handled`` is True when this is a loop
    invocation (a loopable embed runs and produces the flattened child stream,
    or an embed is present but cannot run — logged, ``source`` passed through);
    ``handled`` is False when there is no embed, so the caller runs the operator
    parser instead.
    """
    embed_type = getattr(embed, "type", None)
    handled = True
    stream = source

    if embed and embed_type and embed.loopable:
        embedder = get_subpipe(embed, context, **embedded_kwargs)
        stream = chain.from_iterable(map(embedder, source))
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

    return handled, stream


async def loop_embed_async_eager(
    embed: AsyncProcessorWrapper | None,
    embedded_kwargs: dict,
    context: Context,
    source: Stream,
    op_module_name: str,
) -> tuple[bool, StreamOrValueStream]:
    """
    Eager-async counterpart of ``loop_embed_sync``: maps the embed over the
    source with ``async_map`` and globally flattens the child streams (current
    pre-Yahoo behavior). See the module docstring for the Phase 2/3 trajectory.
    """
    embed_type = getattr(embed, "type", None)
    handled = True
    stream = source

    if embed and embed_type and embed.loopable:
        embedder = get_subpipe(embed, context, **embedded_kwargs)
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

    return handled, stream
