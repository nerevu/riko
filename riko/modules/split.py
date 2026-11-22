# vim: sw=4:ts=4:expandtab
"""
Splits a stream into branches that each yield every item.

A branch read later than its siblings buffers the items in between, so it still sees
every item. ``RIKO_BRANCH_BUFFER`` caps that buffer, and a run whose branch falls
further behind fails rather than dropping items. Each reader gets its own branch, and
every reader except the first to read an item gets a deep copy of the item. Set
``isolate`` to false to pass the item instead of a copy.

Examples:

    Basic usage::

        >>> from riko.modules.split import pipe
        >>>
        >>> stream1, stream2 = pipe({"x": x} for x in range(5))
        >>> next(stream1)
        {'x': 0}

Attributes:

    OPTS: Splitter decoration options.
    DEFAULTS: Default splitter configuration.

"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from riko.bado.itertools import AsyncTee, as_async
from riko.base._config import settings
from riko.base._iterutils import Tee
from riko.base._logging import get_logger
from riko.types._options import DecorationOptions, Defaults

from ._decorators import splitter

if TYPE_CHECKING:
    from logging import Logger

    from riko.coercion._configs import SplitObjconf
    from riko.types._streams import AsyncCascade, Cascade, Feed, Stream
    from riko.types._wrappers import PipeTuples

logger: Logger = get_logger(__name__)

OPTS: DecorationOptions = DecorationOptions()
DEFAULTS: Defaults = {"splits": 2, "isolate": True}


async def async_parser(  # noqa: RUF029 (async pipe contract)
    stream: Feed, objconf: SplitObjconf, tuples: PipeTuples, **kwargs: object
) -> AsyncCascade:
    """
    Asynchronously splits the source into ``splits`` streaming branches.

    Args:

        stream: The sync or async input stream. Note: this shares the `tuples`
            iterator, so consuming it will consume `tuples` as well.

        objconf: The module configuration: `splits` and `isolate`.

        tuples: Iterable of tuples of (item, objconf): `item` is an element in the
            input stream and `objconf` is the item configuration. Note: this shares
            the `stream` iterator, so consuming it will consume `stream` as well.

    Returns:

        An async iterator over the branches. Each is an async stream of the input.

    Raises:

        PipelineError: When a returned branch falls more than ``RIKO_BRANCH_BUFFER``
            items behind its siblings.

    Examples:

        >>> from riko import run
        >>> from meza.fntools import Objectify
        >>>
        >>> objconf = Objectify({"splits": 2, "isolate": True})
        >>>
        >>> async def read_both():
        ...     stream = ({"x": x} for x in range(5))
        ...     branches = await async_parser(stream, objconf, iter(()))
        ...     first, second = [branch async for branch in branches]
        ...     return (await anext(second), await anext(first))
        >>>
        >>> run(read_both)
        ({'x': 0}, {'x': 0})

    """
    isolate, max_lag = bool(objconf.isolate), settings.branch_buffer
    tee = AsyncTee(as_async(stream), isolate=isolate, max_lag=max_lag)
    branches = tuple(tee.branch() for _ in range(int(objconf.splits)))
    return as_async(branches)


def parser(
    stream: Stream, objconf: SplitObjconf, tuples: PipeTuples, **kwargs: object
) -> Cascade:
    """
    Splits the source into ``splits`` streaming branches.

    Args:

        stream: The input stream. Note: this shares the `tuples` iterator, so consuming
            it will consume `tuples` as well.

        objconf: The module configuration: `splits` and `isolate`.

        tuples: Iterable of tuples of (item, objconf): `item` is an element in the
            input stream and `objconf` is the item configuration. Note: this shares
            the `stream` iterator, so consuming it will consume `stream` as well.

    Returns:

        An iterator over the branches, each a stream of every input item. Reading a
        branch raises ``PipelineError`` once it falls more than ``RIKO_BRANCH_BUFFER``
        items behind its siblings.

    Examples:

        >>> from meza.fntools import Objectify
        >>>
        >>> objconf = Objectify({"splits": 3, "isolate": True})
        >>> stream = ({"x": x} for x in range(5))
        >>> stream1, stream2, stream3 = parser(stream, objconf, iter(()))
        >>> next(stream3)
        {'x': 0}

    """
    isolate, max_lag = bool(objconf.isolate), settings.branch_buffer
    tee = Tee(stream, isolate=isolate, max_lag=max_lag)
    return iter(tuple(tee.branch() for _ in range(int(objconf.splits))))


@splitter(DEFAULTS, is_async=True, **OPTS)
async def async_pipe(*args: Any, **kwargs: object) -> AsyncCascade:
    """
    Asynchronously splits a stream into branches that each yield every item.

    A result branch read later than its siblings buffers the items in between.
    ``RIKO_BRANCH_BUFFER`` caps that buffer, and a run exceeding it fails.

    Args:

        items (Feed): The input stream.

        conf (dict): The module configuration.

            splits (int): The number of branches to create. Numeric strings are cast to
                ints (default: 2).

            isolate (bool): Gives every branch but the first reader a deep copy. Pass
                ``False`` to share items between branches when no branch mutates them
                (default: True).

        context (Context): the run environment

    Yields:

        One async stream per split, each yielding every input item.

    Raises:

        PipelineError: When a returned branch falls more than ``RIKO_BRANCH_BUFFER``
            items behind its siblings.

    Examples:

        >>> from riko import run
        >>>
        >>> async def read_first():
        ...     branches = async_pipe({"x": x} for x in range(5))
        ...     first = await anext(branches)
        ...     return await anext(first)
        >>>
        >>> run(read_first)
        {'x': 0}

    """
    return await async_parser(*args, **kwargs)


@splitter(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> Cascade:
    """
    Splits a stream into branches that each yield every item.

    A result branch read later than its siblings buffers the items in between.
    ``RIKO_BRANCH_BUFFER`` caps that buffer, and a run exceeding it fails.

    Args:

        items (Items): The input stream.

        conf (dict): The module configuration.

            splits (int): The number of branches to create. Numeric strings are cast to
                ints (default: 2).

            isolate (bool): Gives every branch but the first reader a deep copy. Pass
                ``False`` to share items between branches when no branch mutates them
                (default: True).

        context (Context): the run environment

    Yields:

        One stream per split. Each of which yields every input item.

    Raises:

        PipelineError: When a returned branch falls more than ``RIKO_BRANCH_BUFFER``
            items behind its siblings.

    Examples:

        >>> from itertools import count
        >>>
        >>> stream1, stream2 = pipe({"x": x} for x in count())
        >>> next(stream1), next(stream1)
        ({'x': 0}, {'x': 1})
        >>> next(stream2), next(stream2)
        ({'x': 0}, {'x': 1})
        >>> items = [{"x": x} for x in range(5)]
        >>> len(list(pipe(items, conf={"splits": "3"})))
        3
        >>> shared1, shared2 = pipe(items, conf={"isolate": False})
        >>> next(shared1) is next(shared2)
        True

    """
    return parser(*args, **kwargs)
