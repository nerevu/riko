# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipefetch
    ~~~~~~~~~~~~~~~~~~~~~~~~~
    Provides methods for fetching RSS feeds.

    http://pipes.yahoo.com/pipes/docs?doc=sources#FetchFeed
"""

try:
    import speedparser as feedparser
except ImportError:
    import feedparser

    feedparser.USER_AGENT = (
        "pipe2py (feedparser/%s) +https://github.com/ggaughan/pipe2py" %
        feedparser.__version__
    )

from urllib2 import urlopen
from pipe2py.lib.dotdict import DotDict
from pipe2py import util


def pipe_fetch(context=None, _INPUT=None, conf=None, **kwargs):
    """A source that fetches and parses one or more feeds to return the
    entries. Loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : pipeforever pipe or an iterable of items or fields
    conf : {'URL': [{'value': <url>, 'type': 'url'}]}

    Yields
    -------
    _OUTPUT : items
    """
    conf = DotDict(conf)
    urls = util.listize(conf['URL'])

    for item in _INPUT:
        for item_url in urls:
            url = util.get_value(DotDict(item_url), DotDict(item), **kwargs)
            url = util.get_abspath(url)

            if not url:
                continue

            if context and context.verbose:
                print "pipe_fetch loading:", url

            parsed = feedparser.parse(urlopen(url).read())

            for entry in util.gen_entries(parsed):
                yield entry

        if item.get('forever'):
            # _INPUT is pipeforever and not a loop,
            # so we just yield our item once
            break
