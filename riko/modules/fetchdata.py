# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.fetchdata
~~~~~~~~~~~~~~~~~~~~~~
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
from typing import Iterator, cast

import pygogo as gogo

from riko import Objconf, listize
from riko.types.general import BasicArg, Extraction, ItemArg, Items

from . import processor
from riko.bado import coroutine, return_value, io
from riko.parsers import Stringy, any2dict
from riko.utils import auto_close, fetch

OPTS = {"ftype": "none"}
DEFAULTS = {}
logger = gogo.Gogo(__name__, monolog=True).logger


@coroutine  # pyright: ignore[reportArgumentType]
def async_parser(_: BasicArg, extraction: Extraction, objconf: Objconf, skip=False, **kwargs):
    """Asynchronously parses the pipe content

    Args:
        _ (None): Ignored
        objconf (obj): The pipe configuration (an Objectify instance)
        skip (bool): Don't parse the content
        kwargs (dict): Keyword arguments

    Kwargs:
        stream (dict): The original item

    Returns:
        Iter[dict]: The stream of items

    Examples:
        >>> from riko import get_path
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>> from meza.fntools import Objectify
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x)['title'])
        ...     url = get_path('gigs.json')
        ...     objconf = Objectify({'url': url, 'path': 'value.items'})
        ...     d = async_parser(None, None, objconf, stream={})
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        Business System Analyst
    """
    if skip:
        stream = kwargs["stream"]
    else:
        ext = p.splitext(objconf.url)[1].lstrip(".")
        path = objconf.path if isinstance(objconf.path, str) else ".".join(objconf.path)

        f = yield io.async_url_open(objconf.url)  # pyright: ignore[reportCallIssue]
        content = any2dict(f, ext, objconf.html5, path=path)
        stream = auto_close(content, f)

    return_value(stream)


def parser(
    _: BasicArg,
    extraction: Extraction,
    objconf: Objconf,
    skip=False,
    **kwargs
) -> Items | Iterator[Stringy]:
    """Parses the pipe content

    Args:
        _ (None): Ignored
        objconf (obj): The pipe configuration (an Objectify instance)
        skip (bool): Don't parse the content
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
        >>> result = parser(None, None, objconf, stream={})
        >>> next(result)['title']
        'Business System Analyst'
    """
    if skip:
        yield cast(ItemArg, kwargs["stream"])
    else:
        ext = p.splitext(objconf.url)[1].lstrip(".")
        path = ".".join(listize(objconf.path))

        with fetch(**{k: objconf[k] for k in objconf}) as f:
            ext = ext or f.ext
            yield from any2dict(f, ext, objconf.html5, path=path)


@processor(DEFAULTS, isasync=True, **OPTS)  # pyright: ignore[reportArgumentType]
def async_pipe(*args, **kwargs):
    """A source that asynchronously fetches and parses an XML or JSON file to
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
        Deferred: twisted.internet.defer.Deferred stream of items

    Examples:
        >>> from riko import get_path
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x)['title'])
        ...     path = 'value.items'
        ...     conf = {'url': get_path('gigs.json'), 'path': path}
        ...     d = async_pipe(conf=conf)
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        Business System Analyst
    """
    return async_parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args, **kwargs):
    """A source that fetches and parses an XML or JSON file to
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
