# vim: sw=4:ts=4:expandtab
"""
Provides functions for parsing a URL into its six components.

Examples:
    basic usage::

        >>> from riko.modules.urlparse import pipe
        >>>
        >>> item = {'content': 'http://yahoo.com'}
        >>> next(pipe(item))
        {'component': 'scheme', 'content': 'http'}

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options

"""

from collections.abc import Iterator
from urllib.parse import urlparse

import pygogo as gogo

from riko.cast import BasicCastType
from riko.types.configs import UrlParseObjconf
from riko.types.general import Defaults, Extraction, Opts

from . import processor

OPTS: Opts = {"ftype": BasicCastType.TEXT, "field": "content"}
DEFAULTS: Defaults = {"parse_key": "content"}
logger = gogo.Gogo(__name__, monolog=True).logger


def parser(
    url: str, extraction: Extraction, objconf: UrlParseObjconf, **kwargs
) -> Iterator[dict[str, str]]:
    """
    Parsers the pipe content

    Args:
        url (str): The link to parse
        objconf (obj): The pipe configuration (an Objectify instance)
        kwargs (dict): Keyword arguments

    Kwargs:
        assign (str): Attribute to assign parsed content (default: urlparse)
        stream (dict): The original item

    Returns:
        dict: The item

    Examples:
        >>> from meza.fntools import Objectify
        >>>
        >>> objconf = Objectify({'parse_key': 'value'})
        >>> result = parser('http://yahoo.com', None, objconf)
        >>> next(result)
        {'component': 'scheme', 'value': 'http'}

    """
    parsed = urlparse(url)
    items = parsed._asdict().items()
    stream = ({"component": k, objconf.parse_key: v} for k, v in items)
    return stream


@processor(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args, **kwargs) -> Iterator[dict[str, str]]:
    """
    A processor module that asynchronously parses a URL into its components.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        assign (str): Attribute to assign parsed content (default: urlparse)
        field (str): Item attribute to operate on (default: 'content')

    Returns:
       Awaitable: item with parsed content

    Examples:
        >>> from riko.bado import run
        >>>
        >>> async def main():
        ...     result = await async_pipe({'content': 'http://yahoo.com'})
        ...     print(next(result))
        >>>
        >>> run(main)
        {'component': 'scheme', 'content': 'http'}

    """
    return parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args, **kwargs) -> Iterator[dict[str, str]]:
    """
    A processor that parses a URL into its components.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. May contain the key 'parse_key'.

            parse_key (str): Attribute to assign individual tokens (default:
                content)

        assign (str): Attribute to assign parsed content (default: urlparse)
        field (str): Item attribute to operate on (default: 'content')

    Yields:
        dict: an item with parsed content

    Examples:
        >>> item = {'content': 'http://yahoo.com'}
        >>> next(pipe(item))
        {'component': 'scheme', 'content': 'http'}
        >>> conf = {'parse_key': 'value'}
        >>> next(pipe(item, conf=conf, emit=True))
        {'component': 'scheme', 'value': 'http'}

    """
    return parser(*args, **kwargs)
