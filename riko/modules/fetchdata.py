# vim: sw=4:ts=4:expandtab
"""
Provides functions for fetching XML and JSON data sources.

Accesses and extracts data from XML and JSON data sources on the web. This data
can then be converted into an RSS feed or merged with other data in your Pipe.

Examples:
    basic usage::

        >>> from riko import get_path
        >>> from riko.modules.fetchdata import pipe
        >>>
        >>> conf = {'url': get_path('gigs.json'), 'path': 'value.items'}
        >>> next(pipe(conf=conf))['title']
        'Business System Analyst'

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options

"""

from os import path as p
from typing import cast

import pygogo as gogo

from riko import ENCODING, listize
from riko.bado import io
from riko.cast import SourceOpts
from riko.parsers import any2dict
from riko.types.configs import FetchDataObjconf
from riko.types.general import Defaults, Extraction, FileTypes, Item, Stream
from riko.utils import Fetch, auto_close

from . import processor

OPTS = SourceOpts
DEFAULTS = Defaults({"encoding": ENCODING})
logger = gogo.Gogo(__name__, monolog=True).logger


async def async_parser(
    _: Item, extraction: Extraction, objconf: FetchDataObjconf, **kwargs
) -> Stream:
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
        ...     url = get_path('gigs.json')
        ...     objconf = Objectify({'url': url, 'path': 'value.items'})
        ...     result = await async_parser(None, None, objconf)
        ...     print(next(result)['title'])
        >>>
        >>> run(main)
        Business System Analyst

    """
    ext = p.splitext(objconf.url)[1].lstrip(".")
    path = objconf.path if isinstance(objconf.path, str) else ".".join(objconf.path)
    # TODO: Figure out if html/xml files should be parsed as binary too.
    binary = ext == "json"
    f = await io.async_url_open(objconf.url, encoding=objconf.encoding, binary=binary)
    content = any2dict(f, ext, objconf.html5, path=path)
    stream = auto_close(content, f)
    return stream


def parser(
    _: Item, extraction: Extraction, objconf: FetchDataObjconf, **kwargs
) -> Stream:
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
        >>> url = get_path('gigs.json')
        >>> objconf = Objectify({'url': url, 'path': 'value.items'})
        >>> result = parser(None, None, objconf)
        >>> next(result)['title']
        'Business System Analyst'

    """
    ext = p.splitext(objconf.url)[1].lstrip(".")
    paths = cast(list[str], listize(objconf.path))
    path = ".".join(paths)

    with Fetch(objconf.url, encoding=objconf.encoding, binary=(ext == "json")) as f:
        ext = ext or f.ext
        content = cast(FileTypes, f)
        yield from any2dict(content, ext, objconf.html5, path=path)


@processor(DEFAULTS, isasync=True, **OPTS)
async def async_pipe(*args, **kwargs) -> Stream:
    """
    A source that asynchronously fetches and parses an XML or JSON file to
    return the entries.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'url'. May
            contain the keys 'path' or 'html5'.

            url (str): The web site to fetch
            path (str): Dot separated path to extract (default: None, i.e.,
                return entire page)

            html5 (bool): Use the HTML5 parser (default: False)

    Returns:
        Awaitable: stream of items

    Examples:
        >>> from riko import get_path
        >>> from riko.bado import run
        >>>
        >>> async def main():
        ...     path = 'value.items'
        ...     conf = {'url': get_path('gigs.json'), 'path': path}
        ...     result = await async_pipe(conf=conf)
        ...     print(next(result)['title'])
        >>>
        >>> run(main)
        Business System Analyst

    """
    return await async_parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args, **kwargs) -> Stream:
    """
    A source that fetches and parses an XML or JSON file to
    return the entries.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'url'. May
            contain the keys 'path' or 'html5'.

            url (str): The web site to fetch
            path (str): Dot separated path to extract (default: None, i.e.,
                return entire page)

            html5 (bool): Use the HTML5 parser (default: False)

    Returns:
        dict: an iterator of items

    Examples:
        >>> from riko import get_path
        >>>
        >>> conf = {'url': get_path('gigs.json'), 'path': 'value.items'}
        >>> next(pipe(conf=conf))['title']
        'Business System Analyst'
        >>> path = 'appointment'
        >>> conf = {'url': get_path('places.xml'), 'path': path}
        >>> next(pipe(conf=conf))['subject']
        'Bring pizza home'
        >>> conf = {'url': get_path('places.xml'), 'path': ''}
        >>> next(pipe(conf=conf))['reminder']
        '15'
        >>> conf = {'url': get_path('schools.xml'), 'path': 'data.row'}
        >>> next(pipe(conf=conf))['district_name']
        'Turkana'

    """
    return parser(*args, **kwargs)
