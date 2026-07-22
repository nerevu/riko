# vim: sw=4:ts=4:expandtab
"""
Provides functions for fetching text data sources.

Accesses and extracts data from text sources on the web. This data can then be
merged with other data in your Pipe.

Examples:
    basic usage::

        >>> from riko import get_path
        >>> from riko.modules.fetchtext import pipe
        >>>
        >>> conf = {'url': get_path('lorem.txt')}
        >>> next(pipe(conf=conf))
        'What is Lorem Ipsum?'

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options

"""

from collections.abc import Iterator

import pygogo as gogo

from riko import ENCODING
from riko.bado import io
from riko.cast import BasicCastType
from riko.types.configs import FetchTextObjconf
from riko.types.general import Defaults, Extraction, Item, Opts
from riko.utils import Fetch, auto_close

from . import processor

OPTS: Opts = {"ftype": BasicCastType.NONE, "assign": "content"}
DEFAULTS: Defaults = {"encoding": ENCODING}
logger = gogo.Gogo(__name__, monolog=True).logger


async def async_parser(
    _: Item, extraction: Extraction, objconf: FetchTextObjconf, **kwargs
) -> Iterator[str]:
    """
    Asynchronously parses the pipe content

    Args:
        _ (Item): The item (Ignored)
        extraction: Field values extracted from the item (Ignored)
        objconf (obj): The pipe configuration (an Objectify instance)
        kwargs (dict): Keyword arguments

    Kwargs:
        stream (dict): The original item

    Returns:
        Iter[dict]: The stream of items

    Examples:
        >>> from riko import get_path
        >>> from riko.bado import run
        >>> from meza.fntools import Objectify
        >>>
        >>> async def main():
        ...     url = get_path('lorem.txt')
        ...     objconf = Objectify({'url': url, 'encoding': ENCODING})
        ...     result = await async_parser(None, None, objconf, assign='content')
        ...     print(next(result))
        >>>
        >>> run(main)
        What is Lorem Ipsum?

    """
    f = await io.async_url_open(objconf.url, encoding=objconf.encoding)
    stream = auto_close(map(str.strip, f), f)
    return stream


def parser(
    _: Item, extraction: Extraction, objconf: FetchTextObjconf, **kwargs
) -> Iterator[str]:
    """
    Parses the pipe content

    Args:
        _ (Item): The item (Ignored)
        extraction: Field values extracted from the item (Ignored)
        objconf (obj): The pipe configuration (an Objectify instance)
        kwargs (dict): Keyword arguments

    Kwargs:
        stream (dict): The original item

    Returns:
        Iter[dict]: The stream of items

    Examples:
        >>> from riko import get_path
        >>> from meza.fntools import Objectify
        >>>
        >>> url = get_path('lorem.txt')
        >>> objconf = Objectify({'url': url, 'encoding': ENCODING})
        >>> result = parser(None, None, objconf, assign='content')
        >>> next(result)
        'What is Lorem Ipsum?'

    """
    f = Fetch(objconf.url, encoding=objconf.encoding)
    stream = auto_close(map(str.strip, f), f)
    return stream


@processor(DEFAULTS, isasync=True, **OPTS)
async def async_pipe(*args, **kwargs) -> Iterator[str]:
    """
    A source that asynchronously fetches and parses an XML or JSON file to
    return the entries.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'url'. May
            contain the key 'encoding'.

            url (str): The web site to fetch.
            encoding (str): The file encoding (default: utf-8).

        assign (str): Attribute to assign parsed content (default: content)


    Returns:
        Awaitable: stream of items

    Examples:
        >>> from riko import get_path
        >>> from riko.bado import run
        >>>
        >>> async def main():
        ...     conf = {'url': get_path('lorem.txt')}
        ...     result = await async_pipe(conf=conf)
        ...     print(next(result))
        >>>
        >>> run(main)
        What is Lorem Ipsum?

    """
    return await async_parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args, **kwargs) -> Iterator[str]:
    """
    A source that fetches and parses an XML or JSON file to
    return the entries.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'url'. May
            contain the key 'encoding'.

            url (str): The web site to fetch
            encoding (str): The file encoding (default: utf-8).

        assign (str): Attribute to assign parsed content (default: content)

    Returns:
        dict: an iterator of items

    Examples:
        >>> from riko import get_path
        >>>
        >>> conf = {'url': get_path('lorem.txt')}
        >>> next(pipe(conf=conf))
        'What is Lorem Ipsum?'

    """
    return parser(*args, **kwargs)
