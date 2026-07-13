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

from riko import ENCODING, Objconf
from riko.bado import coroutine, io, return_value
from riko.types.general import BasicArg, Extraction, ItemArg
from riko.utils import Fetch, auto_close

from . import processor

OPTS = {"ftype": "none", "assign": "content"}
DEFAULTS = {"encoding": ENCODING}
logger = gogo.Gogo(__name__, monolog=True).logger


@coroutine  # pyright: ignore[reportArgumentType]
def async_parser(
    _: BasicArg, extraction: Extraction, objconf: Objconf, skip=False, **kwargs
):
    """
    Asynchronously parses the pipe content

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
        ...     callback = lambda x: print(next(x))
        ...     url = get_path('lorem.txt')
        ...     objconf = Objectify({'url': url, 'encoding': ENCODING})
        ...     d = async_parser(None, None, objconf, assign='content')
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        What is Lorem Ipsum?

    """
    if skip:
        stream = kwargs["stream"]
    else:
        f = yield io.async_url_open(objconf.url)  # pyright: ignore[reportCallIssue]
        _stream = (line.strip().decode(objconf.encoding) for line in f)
        stream = auto_close(_stream, f)

    return_value(stream)


def parser(
    _: BasicArg, extraction: Extraction, objconf: Objconf, skip=False, **kwargs
) -> ItemArg | Iterator[str]:
    """
    Parses the pipe content

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
        >>> url = get_path('lorem.txt')
        >>> objconf = Objectify({'url': url, 'encoding': ENCODING})
        >>> result = parser(None, None, objconf, assign='content')
        >>> next(result)
        'What is Lorem Ipsum?'

    """
    if skip:
        stream = kwargs["stream"]
    else:
        f = Fetch(**{k: objconf[k] for k in objconf})
        _stream = (line.strip() for line in f)
        stream = auto_close(_stream, f)

    return stream


@processor(DEFAULTS, isasync=True, **OPTS)  # pyright: ignore[reportArgumentType]
def async_pipe(*args, **kwargs):
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
        Deferred: twisted.internet.defer.Deferred stream of items

    Examples:
        >>> from riko import get_path
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x))
        ...     conf = {'url': get_path('lorem.txt')}
        ...     d = async_pipe(conf=conf)
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        What is Lorem Ipsum?

    """
    return async_parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args, **kwargs):
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
