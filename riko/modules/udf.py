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

    OPTS: Processor decoration options.
    DEFAULTS: Default processor configuration.

"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from riko.bado._util import maybe_async
from riko.base._logging import get_logger
from riko.base._require_guards import require_arg

from ._decorators import processor

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from logging import Logger

    from riko.coercion._configs import UdfObjconf
    from riko.types._options import DecorationOptions, Defaults
    from riko.types._streams import Item

logger: Logger = get_logger(__name__)

OPTS: DecorationOptions = {"listize": True, "emit": True}
DEFAULTS: Defaults = {}


async def async_parser(
    item: Item,
    extraction: object,
    objconf: UdfObjconf,
    *,
    func: Callable[[Item], Item | Awaitable[Item]] | None = None,
    **kwargs: object,
) -> Item:
    """
    Asynchronously applies ``func`` to one item.

    Args:

        item: The entry to process.
        extraction: The extracted ``field`` value. Unused.
        objconf: The module configuration. Unused.
        func: The function to apply to the item. Awaited when it is an async
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
    func = require_arg(func, "func", "udf", strict=True)
    return await maybe_async(func, item)


def parser(
    item: Item,
    extraction: object,
    objconf: UdfObjconf,
    *,
    func: Callable[[Item], Item] | None = None,
    **kwargs: object,
) -> Item:
    """
    Applies ``func`` to one item.

    Args:

        item: The entry to process.
        extraction: The extracted ``field`` value. Unused.
        objconf: The module configuration. Unused.
        func: The function to apply to the item. Required.

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
    func = require_arg(func, "func", "udf", strict=True)
    return func(item)


@processor(DEFAULTS, isasync=True, **OPTS)
async def async_pipe(*args: Any, **kwargs: object) -> Item:
    """
    Asynchronously applies an arbitrary (user-defined) function to each item.

    Both iterator and iterable sources are mapped over. See the FAQ's "How does a
    processor map over items?".

    Args:

        item (Item | Items): The entry, or stream of entries, to process.
        conf (dict): The module configuration. Unused.
        context (Context): the run environment

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
        ...     result = async_pipe({"x": 0}, func=func)
        ...     print(await anext(result))
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
        conf (dict): The module configuration. Unused.
        context (Context): the run environment

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
