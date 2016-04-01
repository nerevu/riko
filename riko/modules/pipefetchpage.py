# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.pipefetchpage
~~~~~~~~~~~~~~~~~~~~~~~~~~
Provides functions for fetching web pages.

Fetches the source of a given web site as a string. This data can then be
converted into an RSS feed or merged with other data in your Pipe using the
`regex` module.

Examples:
    basic usage::

        >>> from riko.modules.pipefetchpage import pipe
        >>> from . import FILES
        >>>
        >>> conf = {'url': FILES[5], 'start': '<title>', 'end': '</title>'}
        >>> next(pipe(conf=conf))['content']  # doctest: +ELLIPSIS
        u'CNN.com International - Breaking, World..., Entertainment and...'

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

from builtins import *
from six.moves.urllib.request import urlopen
from twisted.internet.defer import inlineCallbacks, returnValue

from . import processor
from riko.lib import utils
from riko.lib.log import Logger
from riko.lib.tags import get_text
from riko.twisted import utils as tu

OPTS = {'ftype': 'none'}
logger = Logger(__name__).logger


def get_string(content, start, end):
    # TODO: convert relative links to absolute
    # TODO: remove the closing tag if using an HTML tag stripped of HTML tags
    # TODO: clean html with Tidy
    content = content.decode('utf-8')
    start_location = content.find(start) if start else 0
    right = content[start_location + len(start):]
    end_location = right[1:].find(end) + 1 if end else len(right)
    return right[:end_location] if end_location > 0 else right


@inlineCallbacks
def asyncParser(_, objconf, skip, **kwargs):
    """ Asynchronously parses the pipe content

    Args:
        _ (None): Ignored
        objconf (obj): The pipe configuration (an Objectify instance)
        skip (bool): Don't parse the content
        kwargs (dict): Keyword arguments

    Kwargs:
        assign (str): Attribute to assign parsed content (default: content)
        feed (dict): The original item

    Returns:
        Tuple(Iter[dict], bool): Tuple of (feed, skip)

    Examples:
        >>> from twisted.internet.task import react
        >>> from . import FILES
        >>> from riko.lib.utils import Objectify
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x[0])['content'][:32])
        ...     conf = {'url': FILES[5], 'start': '<title>', 'end': '</title>'}
        ...     objconf = Objectify(conf)
        ...     kwargs = {'feed': {}, 'assign': 'content'}
        ...     d = asyncParser(None, objconf, False, **kwargs)
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=tu.FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        CNN.com International - Breaking
    """
    if skip:
        feed = kwargs['feed']
    else:
        url = utils.get_abspath(objconf.url)
        content = yield tu.urlRead(url)
        parsed = get_string(content, objconf.start, objconf.end)
        splits = parsed.split(objconf.token) if objconf.token else [parsed]
        feed = ({kwargs['assign']: chunk} for chunk in splits)

    result = (feed, skip)
    returnValue(result)


def parser(_, objconf, skip, **kwargs):
    """ Parses the pipe content

    Args:
        _ (None): Ignored
        objconf (obj): The pipe configuration (an Objectify instance)
        skip (bool): Don't parse the content

    Returns:
        Tuple(Iter[dict], bool): Tuple of (feed, skip)

    Examples:
        >>> from riko.lib.utils import Objectify
        >>> from . import FILES
        >>>
        >>> conf = {'url': FILES[5], 'start': '<title>', 'end': '</title>'}
        >>> objconf = Objectify(conf)
        >>> kwargs = {'feed': {}, 'assign': 'content'}
        >>> result, skip = parser(None, objconf, False, **kwargs)
        >>> next(result)['content'][:32]
        u'CNN.com International - Breaking'
    """
    if skip:
        feed = kwargs['feed']
    else:
        url = utils.get_abspath(objconf.url)
        content = urlopen(url).read()
        parsed = get_string(content, objconf.start, objconf.end)
        detagged = get_text(parsed) if objconf.detag else parsed
        splits = detagged.split(objconf.token) if objconf.token else [detagged]
        feed = ({kwargs['assign']: chunk} for chunk in splits)

    return feed, skip


@processor(async=True, **OPTS)
def asyncPipe(*args, **kwargs):
    """A source that asynchronously fetches the content of a given web site as
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
        dict: twisted.internet.defer.Deferred item with feeds

    Examples:
        >>> from twisted.internet.task import react
        >>> from . import FILES
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x))
        ...     path = 'value.items'
        ...     conf = {'url': FILES[4], 'start': 'DOCTYPE ', 'end': 'http'}
        ...     d = asyncPipe(conf=conf)
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=tu.FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        {u'content': u'html PUBLIC "-//W3C//DTD XHTML+RDFa 1.0//EN" "'}
    """
    return asyncParser(*args, **kwargs)


@processor(**OPTS)
def pipe(*args, **kwargs):
    """A source that fetches the content of a given web site as a string.

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
        dict: an item on the feed

    Examples:
        >>> from . import FILES
        >>> conf = {'url': FILES[4], 'start': 'DOCTYPE ', 'end': 'http'}
        >>> next(pipe(conf=conf))
        {u'content': u'html PUBLIC "-//W3C//DTD XHTML+RDFa 1.0//EN" "'}
    """
    return parser(*args, **kwargs)
