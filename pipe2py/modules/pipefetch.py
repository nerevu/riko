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
from pipe2py.lib import utils
from pipe2py.lib.dotdict import DotDict


def parse(url, context=None):
    if context and context.verbose:
        print "pipe_fetch loading:", url

    content = urlopen(url).read()
    parsed = speedparser.parse(content)
    results = utils.gen_entries(parsed)
    return results


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
    conf = DotDict(conf)
    url_defs = map(DotDict, utils.listize(conf['URL']))
    get_value = partial(utils.get_value, **kwargs)
    get_urls = lambda i: imap(get_value, url_defs, repeat(i))

    finite = utils.make_finite(_INPUT)
    inputs = imap(DotDict, finite)
    urls = imap(get_urls, inputs)
    flat_urls = utils.multiplex(urls)
    true_urls = ifilter(None, flat_urls)
    abs_urls = imap(utils.get_abspath, true_urls)
    items = imap(parse, abs_urls, repeat(context))
    _OUTPUT = utils.multiplex(items)
    return _OUTPUT
