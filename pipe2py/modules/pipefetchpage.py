# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
pipe2py.modules.pipefetchpage
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Fetches web pages.

Fetches the source of a given web site as a string. This data can then be
converted into an RSS feed or merged with other data in your Pipe using the
`regex` module.
"""

from __future__ import (
    absolute_import, division, print_function, with_statement,
    unicode_literals)

from urllib2 import urlopen
from twisted.internet.defer import inlineCallbacks, returnValue
from twisted.web.client import getPage

from . import processor, FEEDS, FILES
from pipe2py.lib import utils
from pipe2py.lib.log import Logger
from pipe2py.lib.dotdict import DotDict
from pipe2py.twisted import utils as tu

OPTS = {'emit': True}
logger = Logger(__name__).logger


def get_string(content, from_, to):
    # TODO: convert relative links to absolute
    # TODO: remove the closing tag if using an HTML tag
    # TODO: stripped of HTML tags
    # TODO: respect robots.txt
    content = content.decode('utf-8')
    from_location = content.find(from_) if from_ else 0
    right = content[from_location:] if from_location > 0 else content
    to_location = right[1:].find(to) + 1 if to else len(right)
    return right[:to_location] if to_location > 0 else right


@inlineCallbacks
def asyncParser(_, objconf, skip, **kwargs):
    if skip:
        tokens = None
    else:
        url = utils.get_abspath(objconf.url)
        content = yield tu.urlRead(url)
        parsed = get_string(content, objconf.from_, objconf.to)
        splits = parsed.split(objconf.token) if objconf.token else [parsed]
        tokens = ({objconf.assign: chunk} for chunk in splits)

    result = (tokens, skip)
    returnValue(result)


def parser(_, objconf, skip, **kwargs):
    if skip:
        tokens = None
    else:
        url = utils.get_abspath(objconf.url)
        content = urlopen(url).read()
        parsed = get_string(content, objconf.from_, objconf.to)
        splits = parsed.split(objconf.token) if objconf.token else [parsed]
        tokens = ({objconf.assign: chunk} for chunk in splits)

    return tokens, skip


@processor(async=True, **OPTS)
def asyncPipe(*args, **kwargs):
    """A source that asynchronously fetches the content of a given web site as
    a string.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        context (obj): pipe2py.Context object
        conf (dict): The pipe configuration

    Returns:
        dict: twisted.internet.defer.Deferred item with feeds

    Examples:
        >>> from twisted.internet.task import react
        >>>
        >>> def run(reactor):
        ...     callback = lambda x: print(x.next())
        ...     path = 'value.items'
        ...     conf = {'url': FILES[4], 'from_': 'DOCTYPE', 'to': 'http'}
        ...     d = asyncPipe(conf=conf)
        ...     return d.addCallbacks(callback, logger.error)
        >>>
        >>> try:
        ...     react(run, _reactor=tu.FakeReactor())
        ... except SystemExit:
        ...     pass
        ...
        {u'content': u'DOCTYPE html PUBLIC "-//W3C//DTD XHTML+RDFa 1.0//EN" "'}
    """
    return asyncParser(*args, **kwargs)


@processor(**OPTS)
def pipe(*args, **kwargs):
    """A source that fetches the content of a given web site as a string.

    Args:
        item (dict): The entry to process
        kwargs (dict): The keyword arguments passed to the wrapper

    Kwargs:
        context (obj): pipe2py.Context object
        conf (dict): The pipe configuration

    Returns:
        dict: an item with feeds

    Examples:
        >>> conf = {'url': FILES[4], 'from_': 'DOCTYPE', 'to': 'http'}
        >>> pipe(conf=conf).next()
        {u'content': u'DOCTYPE html PUBLIC "-//W3C//DTD XHTML+RDFa 1.0//EN" "'}
    """
    return parser(*args, **kwargs)
