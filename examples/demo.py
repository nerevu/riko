# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab

"""
riko demo
~~~~~~~~~

Word Count

    >>> from riko.lib.collections import SyncPipe
    >>> from riko import get_path
    >>>
    >>> url = get_path('users.jyu.fi.html')
    >>> fetch_conf = {
    ...     'url': url, 'start': '<body>', 'end': '</body>', 'detag': True}
    >>> replace_conf = {'rule': {'find': '\\n', 'replace': ' '}}
    >>>
    >>> counts = (SyncPipe('fetchpage', conf=fetch_conf)
    ...     .strreplace(conf=replace_conf, assign='content')
    ...     .stringtokenizer(conf={'delimiter': ' '}, emit=True)
    ...     .count()
    ...     .output)
    >>>
    >>> next(counts)
    {u'count': 70}

Fetching feeds

    >>> from riko.modules.pipefetch import pipe as fetch
    >>>
    >>> url = get_path('gawker.xml')
    >>> intersection = [
    ...     'author', 'author.name', 'author.uri', 'dc:creator', 'id', 'link',
    ...     'pubDate', 'summary', 'title', 'y:id', 'y:published', 'y:title']
    >>> feed = fetch(conf={'url': url})
    >>> item = next(feed)
    >>> set(item.keys()).issuperset(intersection)
    True
    >>> item['title'], item['link']  # doctest: +ELLIPSIS
    (u'...', u'http...')
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

from twisted.internet.defer import inlineCallbacks
from riko import get_path
from riko.lib.collections import SyncPipe
from riko.twisted.collections import AsyncPipe

replace_conf = {'rule': {'find': '\n', 'replace': ' '}}
url1 = get_path('news.yahoo.com_rss_health.xml')
url2 = get_path('www.caltrain.com_Fares_farechart.html')
fetch_conf = {
    'url': url2, 'start': '<body>', 'end': '</body>', 'detag': True}


def pipe(test=False):
    s1 = SyncPipe('fetch', test=test, conf={'url': url1}).output
    s2 = (SyncPipe('fetchpage', test=test, conf=fetch_conf)
        .strreplace(conf=replace_conf, assign='content')
        .stringtokenizer(conf={'delimiter': ' '}, emit=True)
        .count()
        .output)

    print(next(s1)['title'], next(s2)['count'])


@inlineCallbacks
def asyncPipe(reactor, test=False):
    s1 = yield AsyncPipe('fetch', test=test, conf={'url': url1}).output
    s2 = yield (AsyncPipe('fetchpage', test=test, conf=fetch_conf)
        .strreplace(conf=replace_conf, assign='content')
        .stringtokenizer(conf={'delimiter': ' '}, emit=True)
        .count()
        .output)

    print(next(s1)['title'], next(s2)['count'])
