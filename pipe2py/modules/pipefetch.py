# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipefetch
    ~~~~~~~~~~~~~~~~~~~~~~~~~
    Provides methods for fetching RSS feeds.

    http://pipes.yahoo.com/pipes/docs?doc=sources#FetchFeed
"""

from __future__ import (
    absolute_import, division, print_function, with_statement,
    unicode_literals)

import speedparser

from functools import partial
from itertools import imap, ifilter, starmap
from urllib2 import urlopen
from twisted.web.client import getPage
# from twisted.internet.threads import deferToThread
from twisted.internet.defer import inlineCallbacks, maybeDeferred, returnValue
from . import get_splits, asyncGetSplits
from pipe2py.lib import utils
from pipe2py.lib.utils import combine_dicts as cdicts
from pipe2py.twisted.utils import asyncImap, asyncStarMap

opts = {'ftype': None, 'parse': False, 'finitize': True}


def get_urls(urls):
    true_urls = ifilter(None, urls)
    abs_urls = imap(utils.get_abspath, true_urls)
    return imap(str, abs_urls)


# Async functions
# from http://blog.mekk.waw.pl/archives/
# 14-Twisted-inlineCallbacks-and-deferredGenerator.html
# http://code.activestate.com/recipes/277099/
@inlineCallbacks
def asyncParseResult(urls, _, _pass):
    # asyncParse = partial(deferToThread, speedparser.parse)
    asyncParse = partial(maybeDeferred, speedparser.parse)
    str_urls = get_urls(urls)
    contents = yield asyncImap(getPage, str_urls)
    parsed = yield asyncImap(asyncParse, contents)
    entries = imap(utils.gen_entries, parsed)
    items = utils.multiplex(entries)
    returnValue(items)


@inlineCallbacks
def asyncPipeFetch(context=None, _INPUT=None, conf=None, **kwargs):
    """A source that asynchronously fetches and parses one or more feeds to
    return the feed entries. Loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : asyncPipe like object (twisted Deferred iterable of items)
    conf : {
        'URL': [
            {'type': 'url', 'value': <url1>},
            {'type': 'url', 'value': <url2>},
            {'type': 'url', 'value': <url3>},
        ]
    }

    Returns
    -------
    _OUTPUT : twisted.internet.defer.Deferred generator of items
    """
    splits = yield asyncGetSplits(_INPUT, conf['URL'], **cdicts(opts, kwargs))
    items = yield asyncStarMap(asyncParseResult, splits)
    _OUTPUT = utils.multiplex(items)
    returnValue(_OUTPUT)


# Synchronous functions
def parse_result(urls, _, _pass):
    str_urls = get_urls(urls)
    contents = (urlopen(url).read() for url in str_urls)
    parsed = imap(speedparser.parse, contents)
    entries = imap(utils.gen_entries, parsed)
    return utils.multiplex(entries)


def pipe_fetch(context=None, _INPUT=None, conf=None, **kwargs):
    """A source that fetches and parses one or more feeds to return the
    entries. Loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : pipeforever pipe or an iterable of items or fields
    conf : {
        'URL': [
            {'type': 'url', 'value': <url1>},
            {'type': 'url', 'value': <url2>},
            {'type': 'url', 'value': <url3>},
        ]
    }

    Returns
    -------
    _OUTPUT : generator of items
    """
    splits = get_splits(_INPUT, conf['URL'], **cdicts(opts, kwargs))
    items = starmap(parse_result, splits)
    _OUTPUT = utils.multiplex(items)
    return _OUTPUT
