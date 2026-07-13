# vim: sw=4:ts=4:expandtab
"""
riko.modules.strconcat
~~~~~~~~~~~~~~~~~~~~~~
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

from riko import Objconf
from riko.types.general import BasicArg, Extraction

from . import processor

OPTS = {"listize": True, "extract": "part"}
DEFAULTS = {}
logger = gogo.Gogo(__name__, monolog=True).logger


def parser(
    _: BasicArg, extraction: Extraction, objconf: Objconf, skip=False, **kwargs
) -> str:
    """
    Parses the pipe content

    Args:
        _ (dict): The item (ignored)
        parts (List[str]): The content to concatenate
        skip (bool): Don't parse the content
        kwargs (dict): Keyword arguments

    Kwargs:
        stream (dict): The original item

    Returns:
        str: The concatenated string

    Examples:
        >>> parser(None, ['one', 'two'], None)
        'onetwo'

    """
    if skip:
        parsed = kwargs["stream"]
    else:
        parsed = "".join(str(p) for p in extraction if p)

    return parsed


@processor(DEFAULTS, isasync=True, **OPTS)  # pyright: ignore[reportArgumentType]
def async_pipe(*args, **kwargs):
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
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x)['strconcat'])
        ...     item = {'title': 'Hello world'}
        ...     part = [{'subkey': 'title', 'type': 'text'}, 's']
        ...     d = async_pipe(item, conf={'part': part})
        ...     return d.addCallbacks(callback, logger.error)
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
def pipe(*args, **kwargs):
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
