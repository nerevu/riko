# vim: sw=4:ts=4:expandtab
"""
riko.modules.typecast
~~~~~~~~~~~~~~~~~~~~~
Provides functions for casting fields into specific types.

Examples:
    basic usage::

        >>> from riko.modules.typecast import pipe
        >>>
        >>> conf = {'type': 'date'}
        >>> next(pipe({'content': '5/4/82'}, conf=conf))['typecast'].year
        1982

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options

"""

import pygogo as gogo

from riko import Objconf
from riko.cast import CastType, cast
from riko.types.general import Extraction, ItemArg

from . import processor

OPTS = {"field": "content"}
DEFAULTS = {"type": "text"}
logger = gogo.Gogo(__name__, monolog=True).logger


def parser(
    content: str, extraction: Extraction, objconf: Objconf, skip=False, **kwargs
) -> ItemArg:
    """
    Parsers the pipe content

    Args:
        content (scalar): The content to cast
        objconf (obj): The pipe configuration (an Objectify instance)
        skip (bool): Don't parse the content
        kwargs (dict): Keyword arguments

    Kwargs:
        assign (str): Attribute to assign parsed content (default: typecast)
        stream (dict): The original item

    Returns:
        dict: The item

    Examples:
        >>> from meza.fntools import Objectify
        >>>
        >>> item = {'content': '1.0'}
        >>> objconf = Objectify({'type': 'int'})
        >>> kwargs = {'stream': item, 'assign': 'content'}
        >>> parser(item['content'], None, objconf, **kwargs)
        1

    """
    if skip:
        value = kwargs["stream"]
    else:
        value = cast(content, CastType(objconf.type)) if objconf.type else content

    return value


@processor(DEFAULTS, isasync=True, **OPTS)  # pyright: ignore[reportArgumentType]
def async_pipe(*args, **kwargs):
    """
    A processor that asynchronously converts a text string into a variety of
    different types, e.g., int, bool, date, etc. Useful as terminal data. Loopable.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. May contain the key 'type'.
            type (str): The object type to cast to. Must be one of 'text', 'int',
            'float', 'bool', 'url', 'location', or 'date' (default: text).

        assign (str): Attribute to assign parsed content (default: typecast)
        field (str): Item attribute to operate on (default: 'content')

    Returns:
       Deferred: twisted.internet.defer.Deferred item with type casted content

    Examples:
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x)['typecast'])
        ...     d = async_pipe({'content': '1.0'}, conf={'type': 'int'})
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        1

    """
    return parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args, **kwargs):
    """
    A processor that converts a text string into a variety of different types, e.g.,
    int, bool, date, etc. Useful as terminal data. Loopable.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. May contain the key 'type'.
            type (str): The object type to cast to. Must be one of 'text', 'int',
            'float', 'bool', 'url', 'location', or 'date' (default: text).

        assign (str): Attribute to assign parsed content (default: typecast)
        field (str): Item attribute to operate on (default: 'content')

    Yields:
        dict: an item with type casted content

    Examples:
        >>> from datetime import datetime as dt
        >>> next(pipe({'content': '1.0'}, conf={'type': 'int'}))['typecast']
        1
        >>> item = {'content': '5/4/82'}
        >>> conf = {'type': 'datetime'}
        >>> date = next(pipe(item, conf=conf, emit=True))
        >>> date.isoformat()
        '1982-05-04T00:00:00-05:00'
        >>> item = {'content': dt(1982, 5, 4).timetuple()}
        >>> date = next(pipe(item, conf=conf, emit=True))
        >>> date.isoformat()
        '1982-05-04T00:00:00-05:00'
        >>> item = {'content': None}
        >>> next(pipe(item, emit=True))
        ''
        >>> conf = {'type': 'bool'}
        >>> next(pipe(item, conf=conf, emit=True))
        False

    """
    # TODO: add option to specify timezone
    return parser(*args, **kwargs)
