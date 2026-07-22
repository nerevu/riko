# vim: sw=4:ts=4:expandtab
"""
Provides functions for fetching web pages.

Fetches the source of a given web site as a string. This data can then be
converted into an RSS feed or merged with other data in your Pipe using the
`regex` module.

Examples:
    basic usage::

        >>> from riko.modules.fetchpage import pipe
        >>> from riko import get_path
        >>>
        >>> url = get_path('cnn.html')
        >>> conf = {'url': url, 'start': '<title>', 'end': '</title>'}
        >>> next(pipe(conf=conf))[:21]
        'CNN.com International'

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options

"""

from collections.abc import Iterator

import pygogo as gogo

from riko import ENCODING
from riko.bado import io
from riko.cast import SourceOpts
from riko.parsers import get_text
from riko.types.configs import FetchPageObjconf
from riko.types.general import Defaults, Extraction, Item
from riko.utils import Fetch, betwix

from . import processor

OPTS = SourceOpts
DEFAULTS = Defaults({"encoding": ENCODING})
logger = gogo.Gogo(__name__, monolog=True).logger


def get_string(content: str, start: str, end: str) -> str:
    # TODO: convert relative links to absolute
    # TODO: remove the closing tag if using an HTML tag stripped of HTML tags
    # TODO: clean html with Tidy
    start_pos = content.find(start) if start else 0
    right = content[start_pos + (len(start) if start else 0) :]
    end_pos = right[1:].find(end) + 1 if end else len(right)
    return right[:end_pos] if end_pos > 0 else right


async def async_parser(
    _: Item, extraction: Extraction, objconf: FetchPageObjconf, **kwargs
) -> Iterator[str]:
    """
    Asynchronously parses the pipe content

    Args:
        _ (Item): The item (Ignored)
        extraction: Field values extracted from the item (Ignored)
        objconf (obj): The pipe configuration (an Objectify instance)
        kwargs (dict): Keyword arguments

    Kwargs:
        assign (str): Attribute to assign parsed content (default: content)
        stream (dict): The original item

    Returns:
        Iter[dict]: The stream of items

    Examples:
        >>> from riko import get_path
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>> from meza.fntools import Objectify
        >>>
        >>> async def run(reactor):
        ...     url = get_path('cnn.html')
        ...     conf = {'url': url, 'start': '<title>', 'end': '</title>'}
        ...     objconf = Objectify(conf)
        ...     kwargs = {'stream': {}, 'assign': 'content'}
        ...     result = await async_parser(None, None, objconf, **kwargs)
        ...     print(next(result)[:32])
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        CNN.com International - Breaking

    """
    content = await io.async_url_read(objconf.url)
    parsed = get_string(content, str(objconf.start), str(objconf.end))
    detagged = get_text(parsed) if objconf.detag else parsed
    split = detagged.split(objconf.token) if objconf.token else [detagged]
    return map(str.strip, split)


def parser(
    _: Item, extraction: Extraction, objconf: FetchPageObjconf, **kwargs
) -> Iterator[str]:
    """
    Parses the pipe content

    Args:
        _ (Item): The item (Ignored)
        extraction: Field values extracted from the item (Ignored)
        objconf (obj): The pipe configuration (an Objectify instance)

    Returns:
        Iter[dict]: The stream of items

    Examples:
        >>> from meza.fntools import Objectify
        >>> from riko import get_path
        >>>
        >>> url = get_path('cnn.html')
        >>> conf = {'url': url, 'start': '<title>', 'end': '</title>'}
        >>> objconf = Objectify(conf)
        >>> kwargs = {'stream': {}, 'assign': 'content'}
        >>> result = parser(None, None, objconf, **kwargs)
        >>> next(result)[:21]
        'CNN.com International'

    """
    with Fetch(objconf.url, encoding=objconf.encoding) as f:
        sliced = betwix(f, objconf.start, objconf.end, True)
        content = "\n".join(sliced)

    parsed = get_string(content, str(objconf.start), objconf.end)
    detagged = get_text(parsed) if objconf.detag else parsed
    split = detagged.split(objconf.token) if objconf.token else [detagged]
    return map(str.strip, split)


@processor(DEFAULTS, isasync=True, **OPTS)
async def async_pipe(*args, **kwargs) -> Iterator[str]:
    """
    A source that asynchronously fetches the content of a given web site as
    a string.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'url'. May
            contain the keys 'start', 'end', 'token', or 'detag'.

            url (str): The web site to fetch
            start (str): The starting string to fetch (exclusive, default:
                None).

            end (str): The ending string to fetch (exclusive, default: None).
            token (str): The tokenizer delimiter string (default: None).
            detag (bool): Remove html tags from content (default: False).

        assign (str): Attribute to assign parsed content (default: content)

    Returns:
        dict: twisted.internet.defer.Deferred item

    Examples:
        >>> from riko import get_path
        >>> from riko.bado import react
        >>> from riko.bado.mock import FakeReactor
        >>>
        >>> async def run(reactor):
        ...     url, path = get_path('bbc.html'), 'value.items'
        ...     conf = {'url': url, 'start': 'DOCTYPE ', 'end': 'http'}
        ...     result = await async_pipe(conf=conf)
        ...     print(next(result))
        >>>
        >>> try:
        ...     react(run, _reactor=FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        html PUBLIC "-//W3C//DTD XHTML+RDFa 1.0//EN" "

    """
    return await async_parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args, **kwargs) -> Iterator[str]:
    """
    A source that fetches the content of a given web site as a string.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'url'. May
            contain the keys 'start', 'end', 'token', or 'detag'.

            url (str): The web site to fetch
            start (str): The starting string to fetch (exclusive, default:
                None).

            end (str): The ending string to fetch (exclusive, default: None).
            token (str): The tokenizer delimiter string (default: None).
            detag (bool): Remove html tags from content (default: False).

        assign (str): Attribute to assign parsed content (default: content)

    Yields:
        dict: item

    Examples:
        >>> from riko import get_path
        >>>
        >>> url = get_path('bbc.html')
        >>> conf = {'url': url, 'start': 'DOCTYPE ', 'end': 'http'}
        >>> next(pipe(conf=conf))
        'html PUBLIC "-//W3C//DTD XHTML+RDFa 1.0//EN" "'

    """
    return parser(*args, **kwargs)
