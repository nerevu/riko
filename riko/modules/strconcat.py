# vim: sw=4:ts=4:expandtab
"""
Provides functions for concatenating strings (aka stringbuilder).

Useful when you need to build a string from multiple substrings, some coded
into the pipe, other parts supplied when the pipe is run.

Examples:
    basic usage::

        >>> from riko.modules.strconcat import pipe
        >>>
        >>> item = {'word': 'hello'}
        >>> part = [{'subkey': 'word', 'type': 'text'}, ' world']
        >>> next(pipe(item, conf={'part': part}))['strconcat']
        'hello world'

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options

"""

import pygogo as gogo

from riko.types.configs import StrconcatObjconf
from riko.types.general import Defaults, Extraction, Item, Opts

from . import processor

OPTS: Opts = {"listize": True, "extract": "part"}
DEFAULTS: Defaults = {}
logger = gogo.Gogo(__name__, monolog=True).logger


def parser(_: Item, extraction: Extraction, objconf: StrconcatObjconf, **kwargs) -> str:
    """
    Parses the pipe content

    Args:
        _ (dict): The item (ignored)
        parts (List[str]): The content to concatenate
        kwargs (dict): Keyword arguments

    Kwargs:
        stream (dict): The original item

    Returns:
        str: The concatenated string

    Examples:
        >>> parser(None, ['one', 'two'], None)
        'onetwo'

    """
    return "".join(str(p) for p in extraction if p)


@processor(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args, **kwargs) -> str:
    """
    A processor module that asynchronously concatenates strings.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'part'.

            part (dict): can be either a str/dict or list of strs/dicts. If dict, Must
                contain one of the following keys: 'subkey' or 'terminal'.

                subkey (str): The item attribute from which to obtain a
                    substring

                terminal (str): The id of a pipe from which to obtain a
                    substring

        assign (str): Attribute to assign parsed content (default: strconcat)

    Returns:
       Deferred: twisted.internet.defer.Deferred item with concatenated content

    Examples:
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> async def run(reactor):
        ...     item = {'title': 'Hello world'}
        ...     part = [{'subkey': 'title', 'type': 'text'}, 's']
        ...     result = await async_pipe(item, conf={'part': part})
        ...     print(next(result)['strconcat'])
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        Hello worlds

    """
    return parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args, **kwargs) -> str:
    """
    A processor that concatenates strings.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'part'.

            part (dict): can be either a str/dict or list of strs/dicts. If dict, Must
                contain one of the following keys: 'subkey' or 'terminal'.

                subkey (str): The item attribute from which to obtain a
                    substring

                terminal (str): The id of a pipe from which to obtain a
                    substring

        assign (str): Attribute to assign parsed content (default: strconcat)

    Yields:
        dict: an item with concatenated content

    Examples:
        >>> item = {'img': {'src': 'http://www.site.com'}}
        >>> part = ['<img src="', {'subkey': 'img.src', 'type': 'text'}, '">']
        >>> conf = {'part': part}
        >>> next(pipe(item, conf=conf))['strconcat']
        '<img src="http://www.site.com">'
        >>> next(pipe(item, conf=conf, assign='result'))['result']
        '<img src="http://www.site.com">'

    """
    return parser(*args, **kwargs)
