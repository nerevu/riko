# vim: sw=4:ts=4:expandtab
"""
Applies an arbitrary (user-defined) function to each item.

``func`` receives one item at a time. Contrast this with the aggregate module,
which hands the whole stream to a single call.

Examples:
    Basic usage::

        >>> from riko.modules.udf import pipe
        >>>
        >>> func = lambda item: {"y": item["x"] + 3}
        >>> next(pipe({"x": 0}, func=func))
        {'y': 3}

Attributes:
    OPTS: Processor wrapper options.
    DEFAULTS: Default processor configuration.

"""

from collections.abc import Callable
from inspect import iscoroutinefunction
from logging import Logger
from typing import Any

import pygogo as gogo

from riko.modules._prepare import require_kwarg
from riko.types._configs import UdfObjconf
from riko.types._options import Defaults, Opts
from riko.types._streams import Item

from . import processor

OPTS: Opts = {"listize": True, "emit": True}
DEFAULTS: Defaults = {}

logger: Logger = gogo.Gogo(__name__, monolog=True).logger


async def async_parser(
    item: Item, extraction: object, objconf: UdfObjconf, **kwargs: object
) -> Item:
    """
    Asynchronously applies ``func`` to one item.

    Args:
        item: The entry to process.
        extraction: The extracted ``field`` value. Unused.
        objconf: The pipe configuration. Unused.

    Kwargs:
        func (callable): The function to apply to the item. Awaited when it is an async
            function. Required.

    Returns:
        Whatever ``func`` returns.

    Raises:
        TypeError: If ``func`` is not given.

    Examples:
        >>> from itertools import repeat
        >>> from riko import run
        >>>
        >>> async def main():
        ...     func = lambda item: {"y": item["x"] + 3}
        ...     print(await async_parser({"x": 0}, None, None, func=func))
        >>>
        >>> run(main)
        {'y': 3}

    """
    func: Callable[[Item], Item] = require_kwarg(kwargs, "func", "udf")
    return await func(item) if iscoroutinefunction(func) else func(item)


def parser(
    item: Item, extraction: object, objconf: UdfObjconf, **kwargs: object
) -> Item:
    """
    Applies ``func`` to one item.

    Args:
        item: The entry to process.
        extraction: The extracted ``field`` value. Unused.
        objconf: The pipe configuration. Unused.

    Kwargs:
        func (callable): The function to apply to the item. Required.

    Returns:
        Whatever ``func`` returns.

    Raises:
        TypeError: If ``func`` is not given.

    Examples:
        >>> from itertools import repeat
        >>>
        >>> func = lambda item: {"y": item["x"] + 3}
        >>> parser({"x": 0}, None, None, func=func)
        {'y': 3}

    """
    func: Callable[[Item], Item] = require_kwarg(kwargs, "func", "udf")
    return func(item)


@processor(DEFAULTS, isasync=True, **OPTS)
async def async_pipe(*args: Any, **kwargs: object) -> Item:
    """
    Asynchronously applies an arbitrary (user-defined) function to each item.

    Both iterator and iterable sources are mapped over. See the FAQ's "How does a
    processor map over items?".

    Args:
        item (Item | Items): The entry, or stream of entries, to process.
        conf (dict): The pipe configuration. Unused.
        context (Context): the execution context

    Kwargs:
        func (callable): The function to apply to each item. Receives the whole item, or
            the ``field`` value when ``field`` is set. Can be either a sync or async
            function. Required.

        field (str): Field whose value is passed to ``func`` in place of the
            item (default: None).

        assign (str): Field the result is merged into the item under. Ignored
            when ``emit`` is True (default: "udf").

        emit (bool): Whether to emit the result in place of the item rather than
            assign it. Overrides ``assign`` (default: True).

    Yields:
        - ``<result>`` when ``emit`` is True (default)
        - ``{<assign>: <result>}`` when ``emit`` is False and no item given
        - merged ``{Item, <assign>: <result>}`` when ``emit`` is False and
          item is given

    Raises:
        TypeError: If ``func`` is not given.

    Examples:
        >>> from riko import run
        >>>
        >>> async def main():
        ...     func = lambda item: {"y": item["x"] + 3}
        ...     result = await async_pipe({"x": 0}, func=func)
        ...     print(next(result))
        >>>
        >>> run(main)
        {'y': 3}

    """
    return await async_parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> Item:
    """
    Applies an arbitrary (user-defined) function to each item.

    Both iterator and iterable sources are mapped over. See the FAQ's "How does a
    processor map over items?".

    Args:
        item (Item | Items): The entry, or stream of entries, to process.
        conf (dict): The pipe configuration. Unused.
        context (Context): the execution context

    Kwargs:
        func (callable): The function to apply to each item. Receives the whole
            item, or the ``field`` value when ``field`` is set. Required.

        field (str): Field whose value is passed to ``func`` in place of the
            item (default: None).

        assign (str): Field the result is merged into the item under. Ignored
            when ``emit`` is True (default: "udf").

        emit (bool): Whether to emit the result in place of the item rather than
            assign it. Overrides ``assign`` (default: True).

    Yields:
        - ``<result>`` when ``emit`` is True (default)
        - ``{<assign>: <result>}`` when ``emit`` is False and no item given
        - merged ``{Item, <assign>: <result>}`` when ``emit`` is False and
          item is given

    Raises:
        TypeError: If ``func`` is not given.

    Examples:
        >>> func = lambda item: {"y": item["x"] + 3}
        >>> next(pipe({"x": 0}, func=func))
        {'y': 3}

    """
    return parser(*args, **kwargs)
