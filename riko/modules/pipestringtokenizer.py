# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.modules.pipestringtokenizer
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Provides functions for splitting a string into an array of strings.

A delimiter string (often just a single character) tells the module where to
split the input string. The delimiter string doesn't appear in the output.

Examples:
    basic usage::

        >>> from riko.modules.pipestringtokenizer import pipe
        >>> next(pipe({'content': 'Once,twice,thrice'}))['stringtokenizer'][0]
        {u'content': 'Once'}

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

from builtins import *

from . import processor
from riko.lib.log import Logger

OPTS = {'ftype': 'text', 'field': 'content'}
DEFAULTS = {
    'delimiter': ',', 'dedupe': False, 'sort': False, 'token_key': 'content'}

logger = Logger(__name__).logger


def parser(content, objconf, skip, **kwargs):
    """ Parses the pipe content

    Args:
        content (str): The content to tokenize
        objconf (obj): The pipe configuration (an Objectify instance)
        skip (bool): Don't parse the content

    Returns:
        Tuple(Iter[dict], bool): Tuple of (feed, skip)

    Examples:
        >>> from riko.lib.utils import Objectify
        >>> objconf = Objectify({'delimiter': '//', 'token_key': 'token'})
        >>> content = 'Once//twice//thrice//no more'
        >>> result, skip = parser(content, objconf, False)
        >>> next(result)
        {u'token': u'Once'}
    """
    if skip:
        feed = kwargs['feed']
    else:
        splits = filter(None, content.split(objconf.delimiter))
        deduped = set(splits) if objconf.dedupe else splits
        chunks = sorted(deduped, key=str.lower) if objconf.sort else deduped
        feed = ({objconf.token_key: chunk} for chunk in chunks)

    return feed, skip


@processor(DEFAULTS, async=True, **OPTS)
def asyncPipe(*args, **kwargs):
    """A processor module that asynchronously splits a string by a delimiter.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. May contain the keys 'delimiter',
            'dedupe', 'sort', 'assign', or 'token_key'.

            delimiter (str): the delimiter string (default: ',')
            dedupe (bool): Remove duplicates (default: False).
            sort (bool): Sort tokens (default: False)
            assign (str): Attribute to assign parsed content (default:
                stringtokenizer)

            token_key (str): Attribute to assign individual tokens (default:
                content)

        field (str): Item attribute from which to obtain the string to be
            tokenized (default: 'content')

    Returns:
        Deferred: twisted.internet.defer.Deferred item with tokenized content

    Examples:
        >>> from twisted.internet.task import react
        >>> from riko.twisted import utils as tu
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(next(x)['stringtokenizer'][0])
        ...     item = {'content': 'Once,twice,thrice,no more'}
        ...     d = asyncPipe(item)
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=tu.FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        {u'content': 'Once'}
    """
    return parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args, **kwargs):
    """A processor that splits a string by a delimiter.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        conf (dict): The pipe configuration. May contain the keys 'delimiter',
            'dedupe', 'sort', 'assign', or 'token_key'.

            delimiter (str): the delimiter string (default: ',')
            dedupe (bool): Remove duplicates (default: False).
            sort (bool): Sort tokens (default: False)
            assign (str): Attribute to assign parsed content (default:
                stringtokenizer)
            token_key (str): Attribute to assign individual tokens (default:
                content)

        field (str): Item attribute from which to obtain the string to be
            tokenized (default: content)

        emit (bool):

    Returns:
        dict: an item with tokenized content

    Examples:
        >>> item = {'description': 'Once//twice//thrice//no more'}
        >>> conf = {'delimiter': '//', 'sort': True}
        >>> kwargs = {'field': 'description', 'assign': 'tokens'}
        >>> next(pipe(item, conf=conf, **kwargs))['tokens'][0]
        {u'content': 'no more'}
        >>> kwargs.update({'emit': True})
        >>> conf.update({'token_key': 'token'})
        >>> next(pipe(item, conf=conf, **kwargs))
        {u'token': 'no more'}
    """
    return parser(*args, **kwargs)
