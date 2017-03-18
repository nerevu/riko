from __future__ import (
    absolute_import, division, print_function, unicode_literals)

from pprint import pprint
from riko import get_path
from riko.bado import coroutine
from riko.collections import SyncPipe, AsyncPipe

p1_conf = {'url': get_path('gigs.json'), 'path': 'value.items'}
p2_conf = {'uniq_key': 'link'}
p3_conf = {
    'combine': 'or',
    'mode': 'block',
    'rule': [{'field': 'title', 'value': 'php', 'op': 'contains'}]}

p4_conf = {'rule': [{'sort_key': 'pubDate', 'sort_dir': 'desc'}]}


def pipe(test=False):
    stream = (SyncPipe('fetchdata', conf=p1_conf, test=test)
        .uniq(conf=p2_conf)
        .filter(conf=p3_conf)
        .sort(conf=p4_conf)
        .list)

    for i in stream:
        pprint(i)

    return stream


@coroutine
def async_pipe(reactor, test=False):
    stream = yield (AsyncPipe('fetchdata', conf=p1_conf, test=test)
        .uniq(conf=p2_conf)
        .filter(conf=p3_conf)
        .sort(conf=p4_conf)
        .output)

    for i in stream:
        pprint(i)
