# vim: sw=4:ts=4:expandtab
"""
Returns a portion of a string.

You enter two numbers to tell the module the starting character position and
the length of the resulting substring. If your input string is "ABCDEFG", then
a start of 2 and length of 4 gives you a resulting string of "CDEF". Notice
that the first character in the original string is 0, not 1.

A length past the end of the string just returns the remainder, so a start of 3
and a length of 100 gives "DEFG".

Examples:
    Basic usage::

        >>> from riko.modules.substr import pipe
        >>>
        >>> conf = {"start": "3", "length": "4"}
        >>> item = {"content": "hello world"}
        >>> next(pipe(item, conf=conf))["substr"]
        'lo w'

Attributes:
    OPTS: Processor wrapper options.
    DEFAULTS: Default processor configuration.

"""

from logging import Logger
from typing import Any

import pygogo as gogo

from riko.cast import BasicCastType
from riko.types.configs import SubstrObjconf
from riko.types.general import Defaults, Extraction, Opts

from . import processor

OPTS: Opts = {
    "ftype": BasicCastType.TEXT,
    "ptype": BasicCastType.INT,
    "field": "content",
}
DEFAULTS: Defaults = {"start": 0, "length": 0}
logger: Logger = gogo.Gogo(__name__, monolog=True).logger


def parser(word: str, _: Extraction, objconf: SubstrObjconf, **kwargs: object) -> str:
    """
    Returns the slice of ``word`` described by the configuration.

    Args:
        word: The string to slice.
        _: The extracted conf value. Unused.
        objconf: The pipe configuration, containing `start` and `length`.

    Returns:
        The substring, or the remainder of ``word`` when ``length`` is 0 or
        runs past the end.

    Examples:
        >>> from meza.fntools import Objectify
        >>>
        >>> item = {"content": "hello world"}
        >>> conf = {"start": 3, "length": 4}
        >>> parser(item["content"], None, Objectify(conf), stream=item)
        'lo w'

    """
    end = int(objconf.start) + int(objconf.length) if objconf.length else None
    return word[objconf.start : end]


@processor(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args: Any, **kwargs: object) -> str:
    """
    Asynchronously returns a substring of an item field.

    Both iterator and iterable sources are mapped over. See the FAQ's "How does a
    processor map over items?".

    Args:
        item (Item | Items): The entry, or stream of entries, to process.

        conf (dict): The pipe configuration. Each value is cast to an int, so a
            numeric string is accepted.

            start (int): Zero-based position to start at (default: 0).

            length (int): Number of characters to return. 0 returns the
                remainder, as does any length past the end (default: 0).

        context (Context): the execution context

    Kwargs:
        field (str): Item attribute to slice. Its value is cast to text first,
            so a missing field yields ``""`` (default: "content").

        assign (str): Field the substring is assigned to. Ignored when ``emit``
            is True (default: "substr").

        emit (bool): Whether to emit the substring in place of the item rather
            than assign it. Overrides ``assign`` (default: False).

    Yields:
        - merged ``{Item, <assign>: <substring>}`` when ``emit`` is False and item
          is given (default)
        - ``{<assign>: <substring>}`` when ``emit`` is False and no item given
        - ``<substring>`` when ``emit`` is True

    Examples:
        >>> from riko import run
        >>>
        >>> async def main():
        ...     conf = {"start": "3", "length": "4"}
        ...     result = await async_pipe({"content": "hello world"}, conf=conf)
        ...     print(next(result)["substr"])
        >>>
        >>> run(main)
        lo w

    """
    return parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> str:
    """
    Returns a substring of an item field.

    Both iterator and iterable sources are mapped over. See the FAQ's "How does a
    processor map over items?".

    Args:
        item (Item | Items): The entry, or stream of entries, to process.

        conf (dict): The pipe configuration. Each value is cast to an int, so a
            numeric string is accepted.

            start (int): Zero-based position to start at (default: 0).

            length (int): Number of characters to return. 0 returns the
                remainder, as does any length past the end (default: 0).

        context (Context): the execution context

    Kwargs:
        field (str): Item attribute to slice. Its value is cast to text first,
            so a missing field yields ``""`` (default: "content").

        assign (str): Field the substring is assigned to. Ignored when ``emit``
            is True (default: "substr").

        emit (bool): Whether to emit the substring in place of the item rather
            than assign it. Overrides ``assign`` (default: False).

    Yields:
        - merged ``{Item, <assign>: <substring>}`` when ``emit`` is False and item
          is given (default)
        - ``{<assign>: <substring>}`` when ``emit`` is False and no item given
        - ``<substring>`` when ``emit`` is True

    Examples:
        >>> conf = {"start": "3", "length": "4"}
        >>> item = {"content": "hello world"}
        >>> next(pipe(item, conf=conf))["substr"]
        'lo w'
        >>> conf = {"start": "3"}
        >>> kwargs = {"conf": conf, "field": "title", "assign": "result"}
        >>> next(pipe({"title": "Greetings"}, **kwargs))["result"]
        'etings'

    """
    return parser(*args, **kwargs)
