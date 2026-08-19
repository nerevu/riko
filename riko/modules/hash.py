# vim: sw=4:ts=4:expandtab
"""
Hashes the text of an item field.

The field value is cast to text before hashing, so a missing field hashes the
empty string.

Examples:
    Basic usage::

        >>> from riko.modules.hash import pipe
        >>>
        >>> next(pipe({"content": "hello world"}))["hash"]
        1921504423

Attributes:
    OPTS: Processor wrapper options.
    DEFAULTS: Default processor configuration.

"""

import ctypes
from logging import Logger
from typing import Any

import pygogo as gogo

from riko.cast import BasicCastType
from riko.types.configs import DynamicConf
from riko.types.general import Defaults, Extraction, Opts

from . import processor

OPTS: Opts = {
    "ftype": BasicCastType.TEXT,
    "ptype": BasicCastType.NONE,
    "field": "content",
}
DEFAULTS: Defaults = {}
logger: Logger = gogo.Gogo(__name__, monolog=True).logger


def parser(
    content: str, extraction: Extraction, objconf: DynamicConf, **kwargs: object
) -> int:
    """
    Returns the unsigned 32-bit hash of ``content``.

    Args:
        content: The value to hash.
        extraction: The extracted conf value. Unused.
        objconf: The pipe configuration. Unused.

    Returns:
        The hash, wrapped to an unsigned 32-bit integer.

    Examples:
        >>> from meza.fntools import Objectify
        >>>
        >>> item = {"content": "hello world"}
        >>> kwargs = {"stream": item}
        >>> parser(item["content"], None, None, **kwargs)
        1921504423

    """
    return ctypes.c_uint(hash(content)).value


@processor(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args: Any, **kwargs: object) -> int:
    """
    Asynchronously hashes an item field.

    Both iterator and iterable sources are mapped over. See the FAQ's "How does a
    processor map over items?".

    Args:
        item (Item | Items): The entry, or stream of entries, to process.
        conf (dict): The pipe configuration. Unused.
        context (Context): the execution context

    Kwargs:
        field (str): Item attribute to hash. Its value is cast to text first,
            so a missing field hashes ``""`` (default: "content").

        assign (str): Field the hash is assigned to. Ignored when ``emit`` is
            True (default: "hash").

        emit (bool): Whether to emit the hash in place of the item rather than
            assign it. Overrides ``assign`` (default: False).

    Yields:
        - merged ``{Item, <assign>: <hash>}`` when ``emit`` is False and item
          is given (default)
        - ``{<assign>: <hash>}`` when ``emit`` is False and no item given
        - ``<hash>`` when ``emit`` is True

    Examples:
        >>> from riko import run
        >>>
        >>> async def main():
        ...     result = await async_pipe({"content": "hello world"})
        ...     print(next(result)["hash"])
        >>>
        >>> run(main)
        1921504423

    """
    return parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> int:
    """
    Hashes an item field.

    Both iterator and iterable sources are mapped over. See the FAQ's "How does a
    processor map over items?".

    Args:
        item (Item | Items): The entry, or stream of entries, to process.
        conf (dict): The pipe configuration. Unused.
        context (Context): the execution context

    Kwargs:
        field (str): Item attribute to hash. Its value is cast to text first,
            so a missing field hashes ``""`` (default: "content").

        assign (str): Field the hash is assigned to. Ignored when ``emit`` is
            True (default: "hash").

        emit (bool): Whether to emit the hash in place of the item rather than
            assign it. Overrides ``assign`` (default: False).

    Yields:
        - merged ``{Item, <assign>: <hash>}`` when ``emit`` is False and item
          is given (default)
        - ``{<assign>: <hash>}`` when ``emit`` is False and no item given
        - ``<hash>`` when ``emit`` is True

    Examples:
        >>> next(pipe({"content": "hello world"}))
        {'content': 'hello world', 'hash': 1921504423}
        >>> kwargs = {"field": "title", "assign": "result"}
        >>> next(pipe({"title": "greeting"}, **kwargs))["result"]
        528683593

    """
    return parser(*args, **kwargs)
