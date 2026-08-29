# vim: sw=4:ts=4:expandtab
"""
Parses a url into its six components.

Produces one item is per component: ``scheme``, ``netloc``, ``path``, ``params``,
``query``, and ``fragment``.

Examples:
    Basic usage::

        >>> from riko.modules.urlparse import pipe
        >>>
        >>> item = {"content": "http://yahoo.com"}
        >>> next(pipe(item))
        {'component': 'scheme', 'content': 'http'}

Attributes:
    OPTS: Processor wrapper options.
    DEFAULTS: Default processor configuration.

"""

from collections.abc import Iterator
from logging import Logger
from typing import Any
from urllib.parse import urlparse

import pygogo as gogo

from riko.cast import BasicCastType
from riko.types._configs import UrlParseObjconf
from riko.types._options import Defaults, Opts

from . import processor

OPTS: Opts = {"ftype": BasicCastType.TEXT, "field": "content"}
DEFAULTS: Defaults = {"parse_key": "content"}
logger: Logger = gogo.Gogo(__name__, monolog=True).logger


def parser(
    url: str, extraction: object, objconf: UrlParseObjconf, **kwargs: object
) -> Iterator[dict[str, str]]:
    """
    Yields one item per url component.

    Args:
        url: The link to parse.
        extraction: The extracted conf value. Unused.
        objconf: The pipe configuration, containing `parse_key`.

    Returns:
        Six items, each ``{"component": <name>, <parse_key>: <value>}``.

    Examples:
        >>> from meza.fntools import Objectify
        >>>
        >>> objconf = Objectify({"parse_key": "value"})
        >>> result = parser("http://yahoo.com", None, objconf)
        >>> next(result)
        {'component': 'scheme', 'value': 'http'}

    """
    parsed = urlparse(url)
    items = parsed._asdict().items()
    return ({"component": k, objconf.parse_key: v} for k, v in items)


@processor(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args: Any, **kwargs: object) -> Iterator[dict[str, str]]:
    """
    Asynchronously parses a url into its components.

    Both iterator and iterable sources are mapped over. See the FAQ's "How does a
    processor map over items?".

    Args:
        item (Item | Items): The entry, or stream of entries, to process.

        conf (dict): The pipe configuration.

            parse_key (str): Field each component value is stored under
                (default: "content").

        context (Context): the execution context

    Kwargs:
        field (str): Item attribute holding the url (default: "content").

        assign (str): Field the components are assigned to. Ignored when ``emit``
            is True (default: "urlparse").

        emit (bool): Whether to emit each component directly rather than assign
            them. Overrides ``assign`` (default: True).

    Yields:
        - ``{"component": <name>, <parse_key>: <value>}`` when ``emit`` is True
          (default)
        - ``{<assign>: <component>}`` when ``emit`` is False and no item given
        - one merged ``{Item, <assign>: [<component>, ...]}`` when ``emit`` is
          False and item is given

    Examples:
        >>> from riko import run
        >>>
        >>> async def main():
        ...     result = await async_pipe({"content": "http://yahoo.com"})
        ...     print(next(result))
        >>>
        >>> run(main)
        {'component': 'scheme', 'content': 'http'}

    """
    return parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> Iterator[dict[str, str]]:
    """
    Parses a url into its components.

    Both iterator and iterable sources are mapped over. See the FAQ's "How does a
    processor map over items?".

    Args:
        item (Item | Items): The entry, or stream of entries, to process.

        conf (dict): The pipe configuration.

            parse_key (str): Field each component value is stored under
                (default: "content").

        context (Context): the execution context

    Kwargs:
        field (str): Item attribute holding the url (default: "content").

        assign (str): Field the components are assigned to. Ignored when ``emit``
            is True (default: "urlparse").

        emit (bool): Whether to emit each component directly rather than assign
            them. Overrides ``assign`` (default: True).

    Yields:
        - ``{"component": <name>, <parse_key>: <value>}`` when ``emit`` is True
          (default)
        - ``{<assign>: <component>}`` when ``emit`` is False and no item given
        - one merged ``{Item, <assign>: [<component>, ...]}`` when ``emit`` is
          False and item is given

    Examples:
        >>> item = {"content": "http://yahoo.com"}
        >>> next(pipe(item))
        {'component': 'scheme', 'content': 'http'}
        >>> conf = {"parse_key": "value"}
        >>> next(pipe(item, conf=conf, emit=True))
        {'component': 'scheme', 'value': 'http'}

    """
    return parser(*args, **kwargs)
