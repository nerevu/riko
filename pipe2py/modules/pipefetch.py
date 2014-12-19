# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipefetch
    ~~~~~~~~~~~~~~~~~~~~~~~~~
    Provides methods for fetching RSS feeds.

    http://pipes.yahoo.com/pipes/docs?doc=sources#FetchFeed
"""


import speedparser

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


def gen_urls(_INPUT, urls, context, **kwargs):
    for item in _INPUT:
        for item_url in urls:
            url = utils.get_value(DotDict(item_url), DotDict(item), **kwargs)
            yield utils.get_abspath(url)

        if item.get('forever'):
            # _INPUT is pipeforever and not a loop,
            # so we just yield our item once
            break


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
    urls = utils.listize(conf['URL'])
    generated_urls = gen_urls(_INPUT, urls, context, **kwargs)
    results = (parse(url, context) for url in generated_urls)
    _OUTPUT = utils.multiplex(results)
    return _OUTPUT

