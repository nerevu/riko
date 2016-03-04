# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
pipe2py.modules.pipestringtokenizer
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Provides functions for spliting a string into an array of strings.

A delimiter string (often just a single character) tells the module where to
split the input string. The delimiter string doesn't appear in the output.

Examples:
    basic usage::

        >>> from pipe2py.modules.pipestringtokenizer import pipe
        >>> pipe( {'content': 'Once,twice,thrice'}).next()
        {u'content': u'Once'}

Attributes:
    OPTS (dict): The default pipe options
    DEFAULTS (dict): The default parser options
"""

from __future__ import (
    absolute_import, division, print_function, with_statement,
    unicode_literals)

from twisted.internet.defer import maybeDeferred
from . import processor
from pipe2py.lib.utils import combine_dicts as cdicts
from pipe2py.lib.log import Logger

OPTS = {'ftype': 'text', 'emit': True}
DEFAULTS = {'delimiter': ',', 'dedupe': False, 'sort': False}
logger = Logger(__name__).logger


def parser(content, objconf, skip, **kwargs):
    """ Parses the pipe content

    Args:
        objconf (obj): An Objectify instance
        content (str): The content to tokenize
        skip (bool): Don't parse the content

    Returns:
        List(dict): the tokenized content

    Examples:
        >>> from pipe2py.lib.utils import Objectify
        >>> objconf = Objectify({'delimiter': '//', 'assign': 'token'})
        >>> content = 'Once//twice//thrice//no more'
        >>> result, skip = parser(content, objconf, False)
        >>> result.next()
        {u'token': u'Once'}
    """
    if skip:
        tokens = None
    else:
        splits = filter(None, content.split(objconf.delimiter))
        deduped = set(splits) if objconf.dedupe else splits
        chunks = sorted(deduped, key=unicode.lower) if objconf.sort else deduped
        tokens = ({objconf.assign: chunk} for chunk in chunks)

    return tokens, skip


@processor(DEFAULTS, async=True, **OPTS)
def asyncPipe(*args, **kwargs):
    """A processor module that asynchronously splits a string by a delimiter.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        context (obj): pipe2py.Context object
        conf (dict): The pipe configuration

    Returns:
        dict: an item with tokenized content

    Examples:
        >>> from twisted.internet.task import react
        >>> from pipe2py.twisted import utils as tu
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(x.next())
        ...     item = {'content': 'Once,twice,thrice,no more'}
        ...     d = asyncPipe(item)
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=tu.FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        {u'content': u'Once'}
    """
    return parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args, **kwargs):
    """A processor that splits a string by a delimiter.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        context (obj): pipe2py.Context object
        conf (dict): The pipe configuration. May contain the keys 'delimeter',
            'dedupe', 'sort', or 'assign'.

            delimeter (str): the delimiter string (default: ',')
            dedupe (bool): Remove duplicates (default: False).
            sort (bool): Sort tokens (default: False)
            assign (str): Attribute to (default: content)

        field (str): Item attribute from which to obtain the string to be
            tokenized (default: content)

    Returns:
        dict: an item with tokenized content

    Examples:
        >>> item = {'description': 'Once//twice//thrice//no more'}
        >>> conf = {'delimiter': '//', 'assign': 'token', 'sort': True}
        >>> kwargs = {'field': 'description'}
        >>> pipe(item, conf=conf, **kwargs).next()
        {u'token': u'no more'}
    """
    return parser(*args, **kwargs)
