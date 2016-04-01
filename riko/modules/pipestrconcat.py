# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.pipestrconcat
~~~~~~~~~~~~~~~~~~~~~~~~~~
Provides functions for concatenating strings (aka stringbuilder).

Useful when you need to build a string from multiple substrings, some coded
into the pipe, other parts supplied when the pipe is run.

Examples:
    basic usage::

        >>> from riko.modules.pipestrconcat import pipe
        >>> item = {'word': 'hello'}
        >>> part = [{'subkey': 'word'}, {'value': ' world'}]
        >>> next(pipe(item, conf={'part': part}))['strconcat']
        u'hello world'

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

from builtins import *

from . import processor
from riko.lib.log import Logger

OPTS = {'listize': True, 'extract': 'part'}
logger = Logger(__name__).logger


def parser(_, parts, skip, **kwargs):
    """ Parses the pipe content

    Args:
        _ (dict): The item (ignored)
        parts (List[dict]): The content to concatenate
        skip (bool): Don't parse the content
        kwargs (dict): Keyword arguments

    Kwargs:
        feed (dict): The original item

    Returns:
        Tuple(str, bool): Tuple of (the concatenated string, skip)

    Examples:
        >>> parser(None, ['one', 'two'], False)[0]
        u'onetwo'
    """
    try:
        parsed = kwargs['feed'] if skip else ''.join(parts)
    except UnicodeDecodeError:
        decoded = [p.decode('utf-8') for p in parts]
        parsed = ''.join(decoded)

    return parsed, skip


@processor(async=True, **OPTS)
def asyncPipe(*args, **kwargs):
    """A processor module that asynchronously concatenates strings.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'part'.

            part (dict): can be either a dict or list of dicts. Must contain
                one of the following keys: 'value', 'subkey', or 'terminal'.

                value (str): The substring value
                subkey (str): The item attribute from which to obtain a
                    substring

                terminal (str): The id of a pipe from which to obtain a
                    substring

        assign (str): Attribute to assign parsed content (default: strconcat)

    Returns:
       Deferred: twisted.internet.defer.Deferred item with concatenated content

    Examples:
        >>> from twisted.internet.task import react
        >>> from riko.twisted import utils as tu
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x)['strconcat'])
        ...     item = {'title': 'Hello world'}
        ...     part = [{'subkey': 'title'}, {'value': 's'}]
        ...     d = asyncPipe(item, conf={'part': part})
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=tu.FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        Hello worlds
    """
    return parser(*args, **kwargs)


@processor(**OPTS)
def pipe(*args, **kwargs):
    """A processor that concatenates strings.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. Must contain the key 'part'.

            part (dict): can be either a dict or list of dicts. Must contain
                one of the following keys: 'value', 'subkey', or 'terminal'.

                value (str): The substring value
                subkey (str): The item attribute from which to obtain a
                    substring

                terminal (str): The id of a pipe from which to obtain a
                    substring

        assign (str): Attribute to assign parsed content (default: strconcat)

    Yields:
        dict: an item with concatenated content

    Examples:
        >>> item = {'img': {'src': 'http://www.site.com'}}
        >>> part = [
        ...     {'value': '<img src="'}, {'subkey': 'img.src'}, {'value': '">'}
        ... ]
        >>> next(pipe(item, conf={'part': part}))['strconcat']
        u'<img src="http://www.site.com">'
        >>> next(pipe(item, conf={'part': part}, assign='result'))['result']
        u'<img src="http://www.site.com">'
    """
    return parser(*args, **kwargs)
