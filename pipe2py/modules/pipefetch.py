# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipefetch
    ~~~~~~~~~~~~~~~~~~~~~~~~~
    Provides methods for fetching RSS feeds.

    http://pipes.yahoo.com/pipes/docs?doc=sources#FetchFeed
"""


import speedparser

from functools import partial
from itertools import repeat, imap, ifilter
from urllib2 import urlopen
from twisted.web.client import getPage
from twisted.internet.defer import inlineCallbacks, maybeDeferred, returnValue
from pipe2py.lib import utils
from pipe2py.lib.dotdict import DotDict
from pipe2py.twisted.utils import asyncImap


# Common functions
def get_urls(_INPUT, conf, **kwargs):
    finite = utils.make_finite(_INPUT)
    inputs = imap(DotDict, finite)
    url_defs = map(DotDict, utils.listize(conf['URL']))
    get_value = partial(utils.get_value, **kwargs)
    get_urls = lambda i: imap(get_value, url_defs, repeat(i))
    urls = imap(get_urls, inputs)
    flat_urls = utils.multiplex(urls)
    return ifilter(None, flat_urls)

# Async functions
# from http://blog.mekk.waw.pl/archives/
# 14-Twisted-inlineCallbacks-and-deferredGenerator.html
# http://code.activestate.com/recipes/277099/


@inlineCallbacks
def asyncPipeFetch(context=None, _INPUT=None, conf=None, **kwargs):
    """A source that asynchronously fetches and parses one or more feeds to
    return the feed entries. Loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : asyncPipe like object (twisted Deferred iterable of items)
    conf : {'URL': [{'value': <url>, 'type': 'url'}]}

    Returns
    -------
    _OUTPUT : twisted.internet.defer.Deferred generator of items
    """
    _input = yield _INPUT
    urls = get_urls(_input, conf, **kwargs)
    asyncParse = partial(maybeDeferred, speedparser.parse)
    abs_urls = imap(utils.get_abspath, urls)
    contents = yield asyncImap(getPage, abs_urls)
    parsed = yield asyncImap(asyncParse, contents)
    items = imap(utils.gen_entries, parsed)
    _OUTPUT = utils.multiplex(items)
    returnValue(_OUTPUT)


# Synchronous functions
def pipe_fetch(context=None, _INPUT=None, conf=None, **kwargs):
    """A source that fetches and parses one or more feeds to return the
    entries. Loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : pipeforever pipe or an iterable of items or fields
    conf : {'URL': [{'value': <url>, 'type': 'url'}]}

    Returns
    -------
    _OUTPUT : generator of items
    """
    urls = get_urls(_INPUT, conf, **kwargs)
    abs_urls = imap(utils.get_abspath, urls)
    contents = imap(lambda url: urlopen(url).read(), abs_urls)
    parsed = imap(speedparser.parse, contents)
    items = imap(utils.gen_entries, parsed)
    _OUTPUT = utils.multiplex(items)
    return _OUTPUT
