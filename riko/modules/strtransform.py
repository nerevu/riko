# vim: sw=4:ts=4:expandtab
"""
Applies a named ``str`` method to an item field.

``transform`` names any method in ``ATTRS`` — ``capitalize``, ``lower``, ``upper``,
``swapcase``, ``title``, ``strip``, ``rstrip``, ``lstrip``, ``replace``, ``count``,
``find``, ``zfill``. You can provide a list of several rules; each runs on the previous
one's result.

Examples:
    Basic usage::

        >>> from riko.modules.strtransform import pipe
        >>>
        >>> conf = {"rule": {"transform": "title"}}
        >>> item = {"content": "hello world"}
        >>> next(pipe(item, conf=conf))["strtransform"]
        'Hello World'

Attributes:
    ATTRS: The ``str`` methods ``transform`` may name.
    OPTS: Processor wrapper options.
    DEFAULTS: Default processor configuration.

"""

from collections.abc import Sequence
from functools import reduce
from logging import Logger
from typing import Any

import pygogo as gogo

from riko._iterutils import listize
from riko.bado.itertools import coop_reduce
from riko.cast import BasicCastType
from riko.types.configs import StrTransformObjconf
from riko.types.general import Defaults, Opts
from riko.types.modules import StrTransformConfRule

from . import processor

OPTS: Opts = {
    "listize": True,
    "ftype": BasicCastType.TEXT,
    "field": "content",
    "extract": "rule",
}
DEFAULTS: Defaults = {}
logger: Logger = gogo.Gogo(__name__, monolog=True).logger

ATTRS = {
    "capitalize",
    "lower",
    "upper",
    "swapcase",
    "title",
    "strip",
    "rstrip",
    "lstrip",
    "zfill",
    "replace",
    "count",
    "find",
}


def reducer(word: str | int, rule: StrTransformConfRule) -> str | int:
    if rule.transform not in ATTRS:
        logger.warning(f"Invalid transformation: {rule.transform}")
        result = word
    else:
        if isinstance(rule.args, str):
            args: Sequence[object] = rule.args.split(",") if rule.args else []
        else:
            args = listize(rule.args)

        result = getattr(word, rule.transform)(*args)

    return result


async def async_parser(
    word: str | int,
    rules: Sequence[StrTransformConfRule],
    objconf: StrTransformObjconf,
    **kwargs: object,
) -> str | int:
    """
    Asynchronously applies each transform rule to ``word``.

    Args:
        word: The string to transform.
        rules: The parsed transform rules.
        objconf: The pipe configuration. Unused.

    Returns:
        The transformed value. ``count`` and ``find`` return an int rather than
        a string.

    Examples:
        >>> from riko import run
        >>> from meza.fntools import Objectify
        >>>
        >>> async def main():
        ...     item = {"content": "hello world"}
        ...     conf = {"rule": {"transform": "title"}}
        ...     rule = Objectify(conf["rule"])
        ...     result = await async_parser(item["content"], [rule], None, stream=item)
        ...     print(result)
        >>>
        >>> run(main)
        Hello World

    """
    return await coop_reduce(reducer, rules, word)


def parser(
    word: str | int,
    rules: Sequence[StrTransformConfRule],
    objconf: StrTransformObjconf,
    **kwargs: object,
) -> str | int:
    """
    Applies each transform rule to ``word``.

    Args:
        word: The string to transform.
        rules: The parsed transform rules.
        objconf: The pipe configuration. Unused.

    Returns:
        The transformed value. ``count`` and ``find`` return an int rather than
        a string.

    Examples:
        >>> from meza.fntools import Objectify
        >>>
        >>> item = {"content": "hello world"}
        >>> conf = {"rule": {"transform": "title"}}
        >>> rule = Objectify(conf["rule"])
        >>> args = item["content"], [rule], False
        >>> kwargs = {"stream": item, "conf": conf}
        >>> parser(*args, **kwargs)
        'Hello World'

    """
    return reduce(reducer, rules, word)


@processor(DEFAULTS, isasync=True, **OPTS)
async def async_pipe(*args: Any, **kwargs: object) -> str | int:
    """
    Asynchronously applies a named ``str`` method to an item field.

    Both iterator and iterable sources are mapped over. See the FAQ's "How does a
    processor map over items?".

    Args:
        item (Item | Items): The entry, or stream of entries, to process.
        conf (dict): The pipe configuration.

            rule (dict | list): The transform criteria, one dict or a list of
                them. Required.

                transform (str): Name of the ``str`` method to call. Must be
                    one of ``ATTRS``.
                args (str | int | list): Arguments for the method. A string
                    is split on commas, so every argument is a string
                    (``"o,0"`` for ``replace``). Anything else keeps its type —
                    pass a scalar for one argument (``20`` for ``zfill``) or a
                    list for several (``["o", "0", 1]``) (default: None).

        context (Context): the execution context

    Kwargs:
        field (str): Item attribute to transform (default: "content").

        assign (str): Field the result is assigned to. Ignored when ``emit`` is
            True (default: "strtransform").

        emit (bool): Whether to emit the result in place of the item rather than
            assign it. Overrides ``assign`` (default: False).

    Yields:
        - merged ``{Item, <assign>: <value>}`` when ``emit`` is False and item
          is given (default)
        - ``{<assign>: <value>}`` when ``emit`` is False and no item given
        - ``<value>`` when ``emit`` is True

    Raises:
        TypeError: If ``conf`` has no ``rule`` key.

    Notes:
        An unrecognized ``transform`` logs a warning and leaves the field
        unchanged. ``count`` and ``find`` yield an int. For the methods taking
        an int (``zfill``, and the optional arguments of ``replace``, ``count``
        and ``find``) pass ``args`` as a scalar or list, not a string.

    Examples:
        >>> from riko import run
        >>>
        >>> async def main():
        ...     conf = {"rule": {"transform": "title"}}
        ...     result = await async_pipe({"content": "hello world"}, conf=conf)
        ...     print(next(result)["strtransform"])
        >>>
        >>> run(main)
        Hello World

    """
    return await async_parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> str | int:
    """
    Applies a named ``str`` method to an item field.

    Both iterator and iterable sources are mapped over. See the FAQ's "How does a
    processor map over items?".

    Args:
        item (Item | Items): The entry, or stream of entries, to process.
        conf (dict): The pipe configuration.

            rule (dict | list): The transform criteria, one dict or a list of
                them. Required.

                transform (str): Name of the ``str`` method to call. Must be
                    one of ``ATTRS``.

                args (str | int | list): Arguments for the method. A string
                    is split on commas, so every argument is a string
                    (``"o,0"`` for ``replace``). Anything else keeps its type —
                    pass a scalar for one argument (``20`` for ``zfill``) or a
                    list for several (``["o", "0", 1]``) (default: None).

        context (Context): the execution context

    Kwargs:
        field (str): Item attribute to transform (default: "content").

        assign (str): Field the result is assigned to. Ignored when ``emit`` is
            True (default: "strtransform").

        emit (bool): Whether to emit the result in place of the item rather than
            assign it. Overrides ``assign`` (default: False).

    Yields:
        - merged ``{Item, <assign>: <value>}`` when ``emit`` is False and item
          is given (default)
        - ``{<assign>: <value>}`` when ``emit`` is False and no item given
        - ``<value>`` when ``emit`` is True

    Raises:
        TypeError: If ``conf`` has no ``rule`` key.

    Notes:
        An unrecognized ``transform`` logs a warning and leaves the field
        unchanged. ``count`` and ``find`` yield an int. For the methods taking
        an int (``zfill``, and the optional arguments of ``replace``, ``count``
        and ``find``) pass ``args`` as a scalar or list, not a string.

    Examples:
        >>> conf = {"rule": {"transform": "title"}}
        >>> item = {"content": "hello world"}
        >>> next(pipe(item, conf=conf))["strtransform"]
        'Hello World'
        >>> rules = [{"transform": "lower"}, {"transform": "count", "args": "g"}]
        >>> conf = {"rule": rules}
        >>> kwargs = {"conf": conf, "field": "title", "assign": "result"}
        >>> next(pipe({"title": "Greetings"}, **kwargs))["result"]
        2

    """
    return parser(*args, **kwargs)
