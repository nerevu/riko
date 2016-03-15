# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
pipe2py.modules.pipestrconcat
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Provides functions for concatenating strings

Useful when you need to build a string from multiple substrings, some coded
into the pipe, other parts supplied when the pipe is run.

Examples:
    basic usage::

        >>> from pipe2py.modules.pipestrconcat import pipe
        >>> item = {'word': 'hello'}
        >>> part = [{'subkey': 'word'}, {'value': ' world'}]
        >>> pipe(item, conf={'part': part}).next()['strconcat']
        u'hello world'

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""

# aka stringbuilder

from __future__ import (
    absolute_import, division, print_function, with_statement,
    unicode_literals)

from functools import partial
from itertools import starmap, imap
from twisted.internet.defer import inlineCallbacks, returnValue, maybeDeferred

from . import processor
from pipe2py.lib.utils import combine_dicts as cdicts
from pipe2py.twisted.utils import asyncStarMap
from pipe2py.lib.log import Logger

OPTS = {'listize': True, 'extract': 'part'}
logger = Logger(__name__).logger


def parser(_, parts, skip, **kwargs):
    """ Parses the pipe content

    Args:
        _ (dict): The item (ignored)
        parts (List[dict]): The content to concatenate
        skip (bool): Don't parse the content
        kwargs (dict): Keyword argurments

    Kwargs:
        feed (dict): The original item

    Returns:
        str: the concatenated string

    Examples:
        >>> result, skip = parser(None, ['one', 'two'], False)
        >>> result
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
        context (obj): pipe2py.Context object
        conf (dict): The pipe configuration. Must contain the key 'part'. May
            contain the key 'assign'.

            part (dict): can be either a dict or list of dicts. Must contain
                either the key 'value' or 'subkey'.

                value (str): The substring value
                subkey (str): The item attribute from which to obtain a
                    substring

            assign (str): Attribute to assign parsed content (default: strconcat)

        field (str): Item attribute from which to obtain the string to be
            tokenized (default: content)

    Returns:
       Deferred: twisted.internet.defer.Deferred item with concatenated content

    Examples:
        >>> from twisted.internet.task import react
        >>> from pipe2py.twisted import utils as tu
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(x.next()['strconcat'])
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
        context (obj): pipe2py.Context object
        conf (dict): The pipe configuration. Must contain the key 'part'. May
            contain the key 'assign'.

            part (dict): can be either a dict or list of dicts. Must contain
                either the key 'value' or 'subkey'.

                value (str): The substring value
                subkey (str): The item attribute from which to obtain a
                    substring

            assign (str): Attribute to assign parsed content (default: strconcat)

        field (str): Item attribute from which to obtain the string to be
            tokenized (default: content)

    Yields:
        dict: an item with concatenated content

    Examples:
        >>> item = {'img': {'src': 'http://www.site.com'}}
        >>> part = [
        ...     {'value': '<img src="'}, {'subkey': 'img.src'}, {'value': '">'}
        ... ]
        >>> pipe(item, conf={'part': part}).next()['strconcat']
        u'<img src="http://www.site.com">'
        >>> pipe(item, conf={'part': part}, assign='result').next()['result']
        u'<img src="http://www.site.com">'
    """
    return parser(*args, **kwargs)

