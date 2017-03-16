# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab

"""
riko demo
~~~~~~~~~

Word Count

    >>> from riko import get_path
    >>> from riko.collections import SyncPipe
    >>>
    >>> url = get_path('users.jyu.fi.html')
    >>> fetch_conf = {
    ...     'url': url, 'start': '<body>', 'end': '</body>', 'detag': True}
    >>> replace_conf = {'rule': {'find': '\\n', 'replace': ' '}}
    >>>
    >>> counts = (SyncPipe('fetchpage', conf=fetch_conf)
    ...     .strreplace(conf=replace_conf, assign='content')
    ...     .tokenizer(conf={'delimiter': ' '}, emit=True)
    ...     .count()
    ...     .output)
    >>>
    >>> next(counts) == {'count': 70}
    True

Fetching feeds

    >>> from riko.modules import fetch
    >>>
    >>> url = get_path('gawker.xml')
    >>> intersection = [
    ...     'author', 'author.name', 'author.uri', 'dc:creator', 'id', 'link',
    ...     'pubDate', 'summary', 'title', 'y:id', 'y:published', 'y:title']
    >>> feed = fetch.pipe(conf={'url': url})
    >>> item = next(feed)
    >>> set(item).issuperset(intersection)
    True
    >>> item['title'][:24] == 'This Is What A Celebrity'
    True
    >>> item['link'][:23] == 'http://feeds.gawker.com'
    True
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

from riko import get_path
from riko.bado import coroutine
from riko.collections import SyncPipe, AsyncPipe

replace_conf = {'rule': {'find': '\n', 'replace': ' '}}
health = get_path('health.xml')
caltrain = get_path('caltrain.html')
start = '<body id="thebody" class="Level2">'
fetch_conf = {'url': caltrain, 'start': start, 'end': '</body>', 'detag': True}


def pipe(test=False):
    s1 = SyncPipe('fetch', test=test, conf={'url': health}).output
    s2 = (SyncPipe('fetchpage', test=test, conf=fetch_conf)
        .strreplace(conf=replace_conf, assign='content')
        .tokenizer(conf={'delimiter': ' '}, emit=True)
        .count()
        .output)

    print(next(s1)['title'], next(s2)['count'])


@coroutine
def async_pipe(reactor, test=False):
    s1 = yield AsyncPipe('fetch', test=test, conf={'url': health}).output
    s2 = yield (AsyncPipe('fetchpage', test=test, conf=fetch_conf)
        .strreplace(conf=replace_conf, assign='content')
        .tokenizer(conf={'delimiter': ' '}, emit=True)
        .count()
        .output)

    print(next(s1)['title'], next(s2)['count'])
