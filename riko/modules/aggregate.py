# vim: sw=4:ts=4:expandtab
"""
Applies an arbitrary (user-defined) function to a whole stream.

``func`` receives the entire stream and returns the replacement, unlike the udf module,
which applies a function to each item individually. Adds no buffering of its own.
Laziness is inherited from ``func``. A generator stays lazy. The one exception is a
sync ``func``, which receives the collected items of an async stream.

Examples:

    Basic usage::

        >>> from riko.modules.aggregate import pipe
        >>>
        >>> items = [{"x": x} for x in range(5)]
        >>> func = lambda stream: ({"y": item["x"] + 3} for item in stream)
        >>> next(pipe(items, func=func))
        {'y': 3}

Attributes:

    DEFAULTS: Default operator configuration.

"""

from __future__ import annotations

from collections.abc import AsyncIterable
from typing import TYPE_CHECKING, Any

from riko.bado._util import maybe_async
from riko.bado.itertools import materialize
from riko.base._guards import is_async_callable
from riko.base._logging import get_logger
from riko.base._require_guards import require_arg
from riko.coercion._sequences import listize
from riko.types._options import Defaults
from riko.types._streams import Feed, Item, Items, Stream

from ._decorators import operator

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from logging import Logger

    from riko.coercion._configs import AggregateObjconf
    from riko.types._wrappers import PipeTuples

logger: Logger = get_logger(__name__)

type AggregateResult = Item | Items

DEFAULTS: Defaults = Defaults()


async def async_parser(
    stream: Feed,
    objconf: AggregateObjconf,
    tuples: PipeTuples,
    *,
    func: Callable[[Stream], AggregateResult]
    | Callable[[Feed], Awaitable[AggregateResult]]
    | None = None,
    **kwargs: object,
) -> Stream:
    """
    Asynchronously applies ``func`` to the whole stream.

    A result that is not iterable becomes a single item stream; an iterable is
    passed through unchanged.

    Args:

        stream: The input stream, either sync or async. Note: this shares the
            `tuples` iterator, so consuming it will consume `tuples` as well.

        objconf: the item independent configuration. Unused.

        tuples: Iterable of (item, objconf). `item` is an element in the input stream.
            Note: this shares the `stream` iterator, so consuming it will consume
            `stream` as well.

        func: The function to apply to the stream. An async function is awaited and
            receives ``stream`` as is. A sync function given an async stream receives
            its collected items. Required.

    Returns:

        The transformed stream.

    Raises:

        TypeError: If ``func`` is not given.

    Examples:

        >>> from itertools import repeat
        >>> from riko import run
        >>>
        >>> async def main():
        ...     func = lambda stream: ({"y": item["x"] + 3} for item in stream)
        ...     stream = ({"x": x} for x in range(5))
        ...     tuples = zip(stream, repeat(None))
        ...     result = await async_parser(stream, None, tuples, func=func)
        ...     print(next(result))
        >>>
        >>> run(main)
        {'y': 3}

    """
    func = require_arg(func, "func", "aggregate", strict=True)

    if isinstance(stream, AsyncIterable) and not is_async_callable(func):
        source: Feed = await materialize(stream)
    else:
        source = stream

    result = await maybe_async(func, source)
    return iter(listize(result))


def parser(
    stream: Stream,
    objconf: AggregateObjconf,
    tuples: PipeTuples,
    *,
    func: Callable[[Stream], AggregateResult] | None = None,
    **kwargs: object,
) -> Stream:
    """
    Applies ``func`` to the whole stream.

    A result that is not iterable becomes a single item stream; an iterable is
    passed through unchanged.

    Args:

        stream: The input stream. Note: this shares the `tuples` iterator, so consuming
            it will consume `tuples` as well.

        objconf: the item independent configuration. Unused.

        tuples: Iterable of (item, objconf). `item` is an element in the input stream.
            Note: this shares the `stream` iterator, so consuming it will consume
            `stream` as well.

        func: The function to apply to the stream. Required.

    Returns:

        The transformed stream.

    Raises:

        TypeError: If ``func`` is not given.

    Examples:

        >>> from itertools import repeat
        >>>
        >>> func = lambda stream: ({"y": item["x"] + 3} for item in stream)
        >>> stream = ({"x": x} for x in range(5))
        >>> tuples = zip(stream, repeat(None))
        >>> next(parser(stream, None, tuples, func=func))
        {'y': 3}

    """
    func = require_arg(func, "func", "aggregate", strict=True)
    result = func(stream)
    return iter(listize(result))


@operator(DEFAULTS, isasync=True)
async def async_pipe(*args: Any, **kwargs: object) -> Stream:
    """
    Asynchronously applies an arbitrary (user-defined) function to a stream.

    ``func`` is handed the whole stream, not one item at a time. Adds no
    buffering, so laziness is inherited from ``func``.

    Args:

        items (Items): The input stream.
        conf (dict): The module configuration. Unused.
        context (Context): the run environment

    Kwargs:

        func (callable): The function to apply to the stream. Can be either sync or
            async. An async function receives the stream as is. A sync function given an
            async stream receives its collected items. A non-iterable result becomes a
            single item stream. Required.

        assign (str): Field each item is nested under. Ignored when ``emit`` is
            True (default: "aggregate").

        emit (bool): Whether to emit each item directly rather than assign it.
            Overrides ``assign`` (default: True).

    Yields:

        - ``<result>`` when ``emit`` is True (default)
        - ``{<assign>: <result>}`` when ``emit`` is False

    Raises:

        TypeError: If ``func`` is not given.

    Examples:

        >>> from riko import run
        >>>
        >>> async def main():
        ...     func = lambda stream: ({"y": item["x"] + 3} for item in stream)
        ...     items = ({"x": x} for x in range(5))
        ...     result = async_pipe(items, func=func)
        ...     print(await anext(result))
        >>>
        >>> run(main)
        {'y': 3}

    """
    return await async_parser(*args, **kwargs)


@operator(DEFAULTS)
def pipe(*args: Any, **kwargs: object) -> Stream:
    """
    Applies an arbitrary (user-defined) function to a stream.

    ``func`` is handed the whole stream, not one item at a time. Adds no
    buffering, so laziness is inherited from ``func``.

    Args:

        items (Items): The input stream.
        conf (dict): The module configuration. Unused.
        context (Context): the run environment

    Kwargs:

        func (callable): The function to apply to the stream. A result that is
            not iterable becomes a single item stream. Required.

        assign (str): Field each item is nested under. Ignored when ``emit`` is
            True (default: "aggregate").

        emit (bool): Whether to emit each item directly rather than assign it.
            Overrides ``assign`` (default: True).

    Yields:

        - ``<result>`` when ``emit`` is True (default)
        - ``{<assign>: <result>}`` when ``emit`` is False

    Raises:

        TypeError: If ``func`` is not given.

    Examples:

        >>> items = [{"x": x} for x in range(5)]
        >>> func = lambda stream: ({"y": item["x"] + 3} for item in stream)
        >>> next(pipe(items, func=func))
        {'y': 3}

    """
    return parser(*args, **kwargs)
