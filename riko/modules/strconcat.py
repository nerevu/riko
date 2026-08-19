# vim: sw=4:ts=4:expandtab
"""
Concatenates strings (aka stringbuilder).

Useful when you need to build a string from multiple substrings, some coded
into the pipe, other parts supplied when the pipe is run.

Examples:
    Basic usage::

        >>> from riko.modules.strconcat import pipe
        >>>
        >>> item = {"word": "hello"}
        >>> part = [{"subkey": "word", "type": "text"}, " world"]
        >>> next(pipe(item, conf={"part": part}))["strconcat"]
        'hello world'

Attributes:
    OPTS: Processor wrapper options.
    DEFAULTS: Default processor configuration.

"""

from logging import Logger
from typing import Any

import pygogo as gogo

from riko.types.configs import StrconcatObjconf
from riko.types.general import Defaults, Extraction, Item, Opts

from . import processor

OPTS: Opts = {"listize": True, "extract": "part"}
DEFAULTS: Defaults = {}
logger: Logger = gogo.Gogo(__name__, monolog=True).logger


def parser(
    _: Item, extraction: Extraction, objconf: StrconcatObjconf, **kwargs: object
) -> str:
    """
    Joins the resolved parts into one string.

    Unresolved parts are skipped, so a ``subkey`` that finds nothing adds
    nothing.

    Args:
        _: The item. Unused; the parts arrive already resolved.
        extraction: The resolved parts.
        objconf: The pipe configuration. Unused.

    Returns:
        The concatenated string.

    Examples:
        >>> parser(None, ["one", "two"], None)
        'onetwo'

    """
    return "".join(str(p) for p in extraction if p is not None)


@processor(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args: Any, **kwargs: object) -> str:
    """
    Asynchronously concatenates strings into an item field.

    Only an iterator source is mapped over; see the FAQ's "Why does my processor not map
    over a list?".

    Args:
        item (Item | Stream): The entry, or stream of entries, to process.

        conf (dict): The pipe configuration.

            part (str | dict | list): The pieces to join, in order. A single
                piece is wrapped in a list. A str is used verbatim; a dict
                resolves to a value and must hold one of:

                    subkey (str): Item attribute supplying the piece. Dotted keys
                    read nested values, e.g. ``"img.src"``.

                    terminal (str): Id of a wired pipe supplying the piece.

        context (Context): the execution context

    Kwargs:
        assign (str): Field the result is assigned to. Ignored when ``emit`` is
            True (default: "strconcat").

        emit (bool): Whether to emit the string in place of the item rather than
            assign it. Overrides ``assign`` (default: False).

    Yields:
        - merged ``{Item, <assign>: <string>}`` when ``emit`` is False and item
          is given (default)
        - ``{<assign>: <string>}`` when ``emit`` is False and no item given
        - ``<string>`` when ``emit`` is True

    Raises:
        TypeError: If ``conf`` has no ``part`` key.

    Notes:
        Only ``None`` is dropped. So a ``subkey`` that finds nothing adds nothing, while
        other falsy values are kept.

    Examples:
        >>> from riko import run
        >>>
        >>> async def main():
        ...     item = {"title": "Hello world"}
        ...     part = [{"subkey": "title", "type": "text"}, "s"]
        ...     result = await async_pipe(item, conf={"part": part})
        ...     print(next(result)["strconcat"])
        >>>
        >>> run(main)
        Hello worlds

    """
    return parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> str:
    """
    Concatenates strings into an item field.

    Only an iterator source is mapped over; see the FAQ's "Why does my processor not map
    over a list?".

    Args:
        item (Item | Stream): The entry, or stream of entries, to process.

        conf (dict): The pipe configuration.

            part (str | dict | list): The pieces to join, in order. A single
                piece is wrapped in a list. A str is used verbatim; a dict
                resolves to a value and must hold one of:

                    subkey (str): Item attribute supplying the piece. Dotted keys
                    read nested values, e.g. ``"img.src"``.

                    terminal (str): Id of a wired pipe supplying the piece.

        context (Context): the execution context

    Kwargs:
        assign (str): Field the result is assigned to. Ignored when ``emit`` is
            True (default: "strconcat").

        emit (bool): Whether to emit the string in place of the item rather than
            assign it. Overrides ``assign`` (default: False).

    Yields:
        - merged ``{Item, <assign>: <string>}`` when ``emit`` is False and item
          is given (default)
        - ``{<assign>: <string>}`` when ``emit`` is False and no item given
        - ``<string>`` when ``emit`` is True

    Raises:
        TypeError: If ``conf`` has no ``part`` key.

    Notes:
        Only ``None`` is dropped. So a ``subkey`` that finds nothing adds nothing, while
        other falsy values are kept.

    Examples:
        >>> item = {"img": {"src": "http://www.site.com"}}
        >>> part = ['<img src="', {"subkey": "img.src", "type": "text"}, '">']
        >>> conf = {"part": part}
        >>> next(pipe(item, conf=conf))["strconcat"]
        '<img src="http://www.site.com">'
        >>> next(pipe(item, conf=conf, assign="result"))["result"]
        '<img src="http://www.site.com">'

    """
    return parser(*args, **kwargs)
