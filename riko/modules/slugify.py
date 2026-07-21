# vim: sw=4:ts=4:expandtab
"""
Provides functions for slugifying text.

Examples:
    basic usage::

        >>> from riko.modules.slugify import pipe
        >>>
        >>> next(pipe({'content': 'hello world'}))['slugify']
        'hello-world'

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options

"""

import pygogo as gogo
from slugify import slugify

from riko.cast import BasicCastType
from riko.types.configs import SlugifyObjconf
from riko.types.general import Defaults, Opts

from . import processor

OPTS: Opts = {
    "ftype": BasicCastType.TEXT,
    "extract": "separator",
    "field": "content",
    "objectify": False,
}
DEFAULTS: Defaults = {"separator": "-"}
logger = gogo.Gogo(__name__, monolog=True).logger


def parser(word: str, separator: str, objconf: SlugifyObjconf, **kwargs) -> str:
    """
    Parsers the pipe content

    Args:
        word (str): The string to transform
        separator (str): The slug separator.
        kwargs (dict): Keyword arguments

    Kwargs:
        assign (str): Attribute to assign parsed content (default: slugify)
        stream (dict): The original item

    Returns:
        dict: The item

    Examples:
        >>> from meza.fntools import Objectify
        >>>
        >>> item = {'content': 'hello world'}
        >>> parser(item['content'], '-', None, stream=item)
        'hello-world'

    """
    return slugify(word.strip(), separator=separator)


@processor(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args, **kwargs) -> str:
    """
    A processor module that asynchronously slugifies the field of an item.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        assign (str): Attribute to assign parsed content (default: slugify)
        field (str): Item attribute to operate on (default: 'content')

    Returns:
       Deferred: twisted.internet.defer.Deferred item with slugified content

    Examples:
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> async def run(reactor):
        ...     result = await async_pipe({'content': 'hello world'})
        ...     print(next(result)['slugify'])
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        hello-world

    """
    return parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args, **kwargs) -> str:
    """
    A processor that slugifies the field of an item.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. May contain the key 'separator'.
            separator (str): The slug separator (default: '-')

        assign (str): Attribute to assign parsed content (default: slugify)
        field (str): Item attribute to operate on (default: 'content')

    Yields:
        dict: an item with slugified content

    Examples:
        >>> next(pipe({'content': 'hello world'}))['slugify']
        'hello-world'
        >>> conf = {'separator': '_'}
        >>> item = {'title': 'hello world'}
        >>> kwargs = {'conf': conf, 'field': 'title', 'assign': 'result'}
        >>> next(pipe(item, **kwargs))['result']
        'hello_world'

    """
    return parser(*args, **kwargs)
