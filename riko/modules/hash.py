# vim: sw=4:ts=4:expandtab
"""
Provides functions for hashing text.

Note: If the PYTHONHASHSEED environment variable is set to an integer value,
it is used as a fixed seed for generating the hash. Its purpose is to allow
repeatable hashing across python processes and versions. The integer must be a
decimal number in the range [0, 4294967295].

Specifying the value 0 will disable hash randomization. If this variable is set
to `random`, a random value is used to seed the hashes. Hash randomization is
is enabled by default for Python 3.2.3+, and disabled otherwise.

Examples:
    basic usage::

        >>> from riko.modules.hash import pipe
        >>>
        >>> next(pipe({'content': 'hello world'}))['hash']
        1921504423

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options

"""

import ctypes

import pygogo as gogo

from riko import DynamicConf
from riko.cast import BasicCastType
from riko.types.general import Defaults, Extraction, Opts

from . import processor

OPTS: Opts = {
    "ftype": BasicCastType.TEXT,
    "ptype": BasicCastType.NONE,
    "field": "content",
}
DEFAULTS: Defaults = {}
logger = gogo.Gogo(__name__, monolog=True).logger


def parser(content: str, extraction: Extraction, objconf: DynamicConf, **kwargs) -> int:
    """
    Parsers the pipe content

    Args:
        word (str): The string to hash
        _ (None): Ignored.
        kwargs (dict): Keyword arguments

    Kwargs:
        assign (str): Attribute to assign parsed content (default: hash)
        stream (dict): The original item

    Returns:
        dict: The item

    Examples:
        >>> from meza.fntools import Objectify
        >>>
        >>> item = {'content': 'hello world'}
        >>> kwargs = {'stream': item}
        >>> parser(item['content'], None, None, **kwargs)
        1921504423

    """
    return ctypes.c_uint(hash(content)).value


@processor(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args, **kwargs) -> int:
    """
    A processor module that asynchronously hashes the field of an item.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        assign (str): Attribute to assign parsed content (default: hash)
        field (str): Item attribute to operate on (default: 'content')

    Returns:
       Deferred: twisted.internet.defer.Deferred item with hashed content

    Examples:
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> async def run(reactor):
        ...     result = await async_pipe({'content': 'hello world'})
        ...     print(next(result)['hash'])
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        1921504423

    """
    # TODO: figure out why print(next(x)) errs
    return parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args, **kwargs) -> int:
    """
    A processor that hashes the field of an item.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        assign (str): Attribute to assign parsed content (default: hash)
        field (str): Item attribute to operate on (default: 'content')

    Yields:
        dict: an item with hashed content

    Examples:
        >>> next(pipe({'content': 'hello world'}))
        {'content': 'hello world', 'hash': 1921504423}
        >>> kwargs = {'field': 'title', 'assign': 'result'}
        >>> next(pipe({'title': 'greeting'}, **kwargs))['result']
        528683593

    """
    return parser(*args, **kwargs)
