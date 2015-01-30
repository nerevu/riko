# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipefetchdata
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    Provides methods for fetching XML and JSON data sources.

    http://pipes.yahoo.com/pipes/docs?doc=sources#FetchData
"""

from __future__ import (
    absolute_import, division, print_function, with_statement,
    unicode_literals)

from lxml import objectify
from lxml.etree import XMLSyntaxError
from urllib2 import urlopen
from json import loads

from functools import partial
from itertools import imap, starmap
from twisted.internet import defer as df
from twisted.internet.defer import inlineCallbacks, returnValue
from . import get_split, get_dispatch_funcs
from pipe2py.lib import utils
from pipe2py.lib.utils import combine_dicts as cdicts
from pipe2py.twisted import utils as tu

opts = {'listize': False, 'ftype': None}
func = lambda element, i: element.get(i) if element else None


def parse_conf(conf):
    url = utils.get_abspath(conf.URL)
    path = conf.path.split('.') if conf.path else []
    return (url, path, None)


def get_element(url):
    try:
        tree = objectify.parse(urlopen(url))
        root = tree.getroot()
    except XMLSyntaxError:
        element = loads(urlopen(url).read())
    else:
        # print(etree.tostring(element, pretty_print=True))
        element = utils.etree_to_dict(root)

    return element

# Async functions
asyncParseResult = lambda element, path, _: tu.coopReduce(func, path, element)


@inlineCallbacks
def asyncPipeFetchdata(context=None, item=None, conf=None, **kwargs):
    pkwargs = cdicts(opts, kwargs, {'async': True})
    split_conf = yield get_split(item, conf, **pkwargs)[0]
    parsed_conf = parse_conf(split_conf)
    asyncGetElement = partial(df.maybeDeferred, get_element)
    asyncFuncs = get_dispatch_funcs('pass', asyncGetElement, async=True)
    parsed = yield tu.asyncDispatch(parsed_conf, *asyncFuncs)
    result = yield asyncParseResult(*parsed)
    _OUTPUT = utils.gen_items(result)
    returnValue(_OUTPUT)


# Synchronous functions
parse_result = lambda element, path, _: reduce(func, path, element)


def pipe_fetchdata(context=None, item=None, conf=None, **kwargs):
    """A source that fetches and parses an XML or JSON file. Loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    item : pipeforever pipe or an iterable of items or fields
    conf : {
        'URL': {'value': <url>},
        'path': {'value': <dot separated path to data list>}
    }

    Yields
    ------
    _OUTPUT : items

    Examples
    --------
    >>> from os import path as p
    >>> from pipe2py.modules.pipeforever import pipe_forever
    >>> parent = p.dirname(p.dirname(__file__))
    >>> abspath = p.abspath(p.join(parent, 'data', 'gigs.json'))
    >>> path = 'value.items'
    >>> url = "file://%s" % abspath
    >>> conf = {'URL': {'value': url}, 'path': {'value': path}}
    >>> pipe_fetchdata(item=pipe_forever(), conf=conf).next().keys()[:5]
    [u'y:repeatcount', u'description', u'pubDate', u'title', u'y:published']
    >>> abspath = p.abspath(p.join(parent, 'data', 'places.xml'))
    >>> path = 'appointment'
    >>> url = "file://%s" % abspath
    >>> conf = {'URL': {'value': url}, 'path': {'value': path}}
    >>> sorted(pipe_fetchdata(item=pipe_forever(), conf=conf).next().keys())
    [u'alarmTime', u'begin', u'duration', u'places', u'subject', u'uid']
    >>> conf = {'URL': {'value': url}, 'path': {'value': ''}}
    >>> sorted(pipe_fetchdata(item=pipe_forever(), conf=conf).next().keys())
    [u'appointment', 'reminder']
    """
    # todo: iCal and KML
    split_conf = get_split(item, conf, **cdicts(opts, kwargs))[0]
    parsed_conf = parse_conf(split_conf)
    funcs = get_dispatch_funcs('pass', get_element)
    parsed = utils.dispatch(parsed_conf, *funcs)
    result = parse_result(*parsed)
    _OUTPUT = utils.gen_items(result)
    return _OUTPUT
