# vim: sw=4:ts=4:expandtab
"""
Slugifies the text in an item field.

Transliterates the field to ascii, lowercases it, and joins what is left with
``separator``, giving a value safe to use in a url or filename.

Examples:
    Basic usage::

        >>> from riko.modules.slugify import pipe
        >>>
        >>> next(pipe({"content": "hello world"}))["slugify"]
        'hello-world'

Attributes:
    SEPARATOR: The separator used when ``conf`` supplies none.
    OPTS: Processor wrapper options.
    DEFAULTS: Default processor configuration.

"""

from logging import Logger
from typing import Any

import pygogo as gogo
from slugify import slugify

from riko.cast import BasicCastType
from riko.types._configs import SlugifyObjconf
from riko.types._options import Defaults, Opts

from . import processor

SEPARATOR = "-"

OPTS: Opts = {
    "ftype": BasicCastType.TEXT,
    "extract": "separator",
    "field": "content",
    "objectify": False,
}
DEFAULTS: Defaults = {"separator": SEPARATOR}
logger: Logger = gogo.Gogo(__name__, monolog=True).logger


def parser(
    word: str, separator: str | None, objconf: SlugifyObjconf, **kwargs: object
) -> str:
    """
    Slugifies ``word``.

    Args:
        word: The string to slugify.
        separator: The slug separator, or None to use the default.
        objconf: The pipe configuration. Unused.

    Returns:
        The slug.

    Examples:
        >>> item = {"content": "hello world"}
        >>> parser(item["content"], "-", None, stream=item)
        'hello-world'

    """
    sep = SEPARATOR if separator is None else separator
    return slugify(word.strip(), separator=sep)


@processor(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args: Any, **kwargs: object) -> str:
    """
    Asynchronously slugifies the text in an item field.

    Both iterator and iterable sources are mapped over. See the FAQ's "How does a
    processor map over items?".

    Args:
        item (Item | Items): The entry, or stream of entries, to process.
        conf (dict): The pipe configuration.

            separator (str): Joins the slug's words (default: "-").

        context (Context): the execution context

    Kwargs:
        field (str): Item attribute to slugify (default: "content").

        assign (str): Field the slug is assigned to. Ignored when ``emit`` is
            True (default: "slugify").

        emit (bool): Whether to emit the slug in place of the item rather than
            assign it. Overrides ``assign`` (default: False).

    Yields:
        - merged ``{Item, <assign>: <slug>}`` when ``emit`` is False and item is
          given (default)
        - ``{<assign>: <slug>}`` when ``emit`` is False and no item given
        - ``<slug>`` when ``emit`` is True

    Notes:
        A field the item lacks slugifies to ``""``.

    Examples:
        >>> from riko import run
        >>>
        >>> async def main():
        ...     result = await async_pipe({"content": "hello world"})
        ...     print(next(result)["slugify"])
        >>>
        >>> run(main)
        hello-world

    """
    return parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> str:
    """
    Slugifies the text in an item field.

    Both iterator and iterable sources are mapped over. See the FAQ's "How does a
    processor map over items?".

    Args:
        item (Item | Items): The entry, or stream of entries, to process.
        conf (dict): The pipe configuration.

            separator (str): Joins the slug's words (default: "-").

        context (Context): the execution context

    Kwargs:
        field (str): Item attribute to slugify (default: "content").

        assign (str): Field the slug is assigned to. Ignored when ``emit`` is
            True (default: "slugify").

        emit (bool): Whether to emit the slug in place of the item rather than
            assign it. Overrides ``assign`` (default: False).

    Yields:
        - merged ``{Item, <assign>: <slug>}`` when ``emit`` is False and item is
          given (default)
        - ``{<assign>: <slug>}`` when ``emit`` is False and no item given
        - ``<slug>`` when ``emit`` is True

    Notes:
        A field the item lacks slugifies to ``""``.

    Examples:
        >>> next(pipe({"content": "hello world"}))["slugify"]
        'hello-world'
        >>> conf = {"separator": "_"}
        >>> item = {"title": "hello world"}
        >>> kwargs = {"conf": conf, "field": "title", "assign": "result"}
        >>> next(pipe(item, **kwargs))["result"]
        'hello_world'
        >>> next(pipe({"content": "Crème Brûlée & Co."}))["slugify"]
        'creme-brulee-co'

    """
    return parser(*args, **kwargs)
