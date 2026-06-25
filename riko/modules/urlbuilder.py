# vim: sw=4:ts=4:expandtab
"""
Provides functions for building a url from parts

Many URLs are long and complex. Modules like Fetch Feed let you provide a URL
as a starting point for a Pipe, but sometimes you'd like to control how that
URL is constructed. That's what the URL Builder module does.

To see how this works, and why it can be useful, lets look at an example URL:

    http://finance.yahoo.com/rss/headline?s=yhoo

One of Yahoo! Finance's RSS services lets you get news feeds for companies
based on their stock market ticker. The URL above returns news stories related
to Yahoo! (stock ticker YHOO). To get news on another company, for example
General Motors (stock ticker GM), you'd simply change the URL to:

    http://finance.yahoo.com/rss/headline?s=gm

URLs are built from three main parts. The first is a server name, in our
example that's "finance.yahoo.com". The second part is a resource path. That's
everything after the server name, up to (but not including) the question mark
("/rss/headline"). Finally, after the question mark are a series of parameters.

In our example, there's only one parameter, named s. The parameter name and its
value are separated by an equal sign, giving us "s=gm" or "s=yhoo".

If we want to use this service in our Pipe, we can just use a Fetch Feed
module and enter the URL. But then our Pipe is stuck reading data for just one
ticker symbol. We could wire in a URL Input module, but then the user has to
enter the whole URL.

The better way is to use URL Builder. This module constructs a URL for you from
parts. Some parts you may type in, others you may wire in using Text User Input
modules.

Examples:
    basic usage::

        >>> from riko.modules.urlbuilder import pipe
        >>>
        >>> param = {'key': 's', 'value': 'gm'}
        >>> path = ['rss', 'headline']
        >>> base = 'http://finance.yahoo.com'
        >>> conf = {'base': base, 'path': path, 'param': param}
        >>> next(pipe(conf=conf))
        'http://finance.yahoo.com/rss/headline?s=gm'

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options

"""

import re
from collections.abc import Mapping, Sequence
from urllib.parse import urlencode, urljoin

import pygogo as gogo

from riko import Objconf
from riko.types.general import Defaults, Item, Opts
from riko.types.modules import ObjconfParam

from . import processor

OPTS: Opts = {"extract": "param", "listize": True, "emit": True}
DEFAULTS: Defaults = {}
logger = gogo.Gogo(__name__, monolog=True).logger

PATTERN = re.compile(r'[<>:"/\\\|\*%]')


def parser(_: Item, param: Sequence[ObjconfParam], objconf: Objconf, **kwargs) -> str:
    """
    Parsers the pipe content

    Args:
        item (obj): The entry to process (a DotDict instance)
        param (List[Objectify]): Query parameters
        kwargs (dict): Keyword arguments

    Kwargs:
        stream (dict): The original item

    Returns:
        dict: The item

    Examples:
        >>> from meza.fntools import Objectify
        >>>
        >>> param = {'key': 's', 'value': 'gm'}
        >>> path = ['rss', 'headline']
        >>> base = 'http://finance.yahoo.com'
        >>> conf = {'base': base, 'path': path, 'param': param}
        >>> parser({}, [Objectify(param)], Objectify(conf))
        'http://finance.yahoo.com/rss/headline?s=gm'

    """
    if isinstance(objconf.path, str):
        paths = [objconf.path]
    elif isinstance(objconf.path, Mapping):
        logger.error(f"Path should be a string or list of strings, not {objconf.path}")
        paths = []
    elif objconf.path:
        paths = objconf.path
    else:
        paths = []

    encoded = urlencode([(p.key, p.value) for p in param if p.key])
    joined = urljoin(str(objconf.base), "/".join(paths))
    stream = f"{joined}?{encoded}" if encoded else joined

    if objconf.ext:
        substituted = re.sub(PATTERN, "_", stream)
        stream = f"{substituted}.{objconf.ext}"

    return stream


@processor(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args, **kwargs) -> str:
    """
    A source that asynchronously builds a url.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'base'. May
            contain the keys 'param' or 'path'.

            base (str): the sever name
            path (str): the resource path
            param (dict): can be either a dict or list of dicts. Must contain
                the keys 'key' and 'value'.

                key (str): the parameter name
                value (str): the parameter value

    Returns:
        dict: twisted.internet.defer.Deferred an iterator of items

    Examples:
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> async def run(reactor):
        ...     param = {'key': 's', 'value': 'gm'}
        ...     path = ['rss', 'headline']
        ...     base = 'http://finance.yahoo.com'
        ...     conf = {'base': base, 'path': path, 'param': param}
        ...     result = await async_pipe(conf=conf)
        ...     print(next(result))
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        http://finance.yahoo.com/rss/headline?s=gm

    """
    return parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args, **kwargs) -> str:
    """
    A source that builds a url.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'base'. May
            contain the keys 'param' or 'path'.

            base (str): the sever name
            ext (str): the file extension (for offline files)
            path (str): the resource path

            param (dict): can be either a dict or list of dicts. Must contain
                the keys 'key' and 'value'.

                key (str): the parameter name
                value (str): the parameter value

    Yields:
        dict: a url item

    Examples:
        >>> param = {'key': 's', 'value': 'gm'}
        >>> path = ['rss', 'headline']
        >>> base = 'http://finance.yahoo.com'
        >>> conf = {'base': base, 'path': path, 'param': param}
        >>> next(pipe(conf=conf))
        'http://finance.yahoo.com/rss/headline?s=gm'

    """
    return parser(*args, **kwargs)
