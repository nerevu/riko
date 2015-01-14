# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipefetchdata
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    Provides methods for fetching XML and JSON data sources.

    http://pipes.yahoo.com/pipes/docs?doc=sources#FetchData
"""

from lxml import objectify
from lxml.etree import XMLSyntaxError
from urllib2 import urlopen

try:
    from json import loads
except (ImportError, AttributeError):
    from simplejson import loads

from functools import partial
from itertools import imap
from twisted.internet.defer import inlineCallbacks, maybeDeferred, returnValue
from . import get_broadcast_funcs as get_funcs
from pipe2py.lib import utils
from pipe2py.lib.dotdict import DotDict
from pipe2py.twisted.utils import asyncGather


# Common functions
def get_parsed(_INPUT, conf, **kwargs):
    finite = utils.make_finite(_INPUT)
    inputs = imap(DotDict, finite)
    broadcast_funcs = get_funcs(conf, ftype=None, listize=False, **kwargs)
    confs = imap(broadcast_funcs[0], inputs)
    splits = imap(parse_conf, confs)
    return utils.dispatch(splits, get_element, utils.passthrough)


def parse_result(element, path):
    for i in path:
        element = element.get(i) if element else None

    return element


def parse_conf(conf):
    url = utils.get_abspath(conf.URL)
    path = conf.path.split('.') if conf.path else []
    return (url, path)


def get_element(url):
    try:
        tree = objectify.parse(urlopen(url))
        root = tree.getroot()
    except XMLSyntaxError:
        element = loads(urlopen(url).read())
    else:
        # print etree.tostring(element, pretty_print=True)
        element = utils.etree_to_dict(root)

    return element


# Async functions
@inlineCallbacks
def asyncPipeFetchdata(context=None, _INPUT=None, conf=None, **kwargs):
    _input = yield _INPUT
    parsed = get_parsed(_input, conf, **kwargs)
    results = yield asyncGather(parsed, partial(maybeDeferred, parse_result))
    items = imap(utils.gen_items, results)
    _OUTPUT = utils.multiplex(items)
    returnValue(_OUTPUT)


# Synchronous functions
def pipe_fetchdata(context=None, _INPUT=None, conf=None, **kwargs):
    """A source that fetches and parses an XML or JSON file. Loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : pipeforever pipe or an iterable of items or fields
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
    >>> pipe_fetchdata(_INPUT=pipe_forever(), conf=conf).next().keys()[:5]
    [u'y:repeatcount', u'description', u'pubDate', u'title', u'y:published']
    >>> abspath = p.abspath(p.join(parent, 'data', 'places.xml'))
    >>> path = 'appointment'
    >>> url = "file://%s" % abspath
    >>> conf = {'URL': {'value': url}, 'path': {'value': path}}
    >>> sorted(pipe_fetchdata(_INPUT=pipe_forever(), conf=conf).next().keys())
    [u'alarmTime', u'begin', u'duration', u'places', u'subject', u'uid']
    >>> conf = {'URL': {'value': url}, 'path': {'value': ''}}
    >>> sorted(pipe_fetchdata(_INPUT=pipe_forever(), conf=conf).next().keys())
    [u'appointment', 'reminder']
    """
    # todo: iCal and KML
    parsed = get_parsed(_INPUT, conf, **kwargs)
    results = utils.gather(parsed, parse_result)
    items = imap(utils.gen_items, results)
    _OUTPUT = utils.multiplex(items)
    return _OUTPUT
