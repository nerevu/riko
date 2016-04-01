from __future__ import (
    absolute_import, division, print_function, unicode_literals)

from pprint import pprint
from twisted.internet.defer import inlineCallbacks
from riko.lib.collections import SyncPipe
from riko.twisted.collections import AsyncPipe

p68_conf = {'url': 'file://data/gigs.json', 'path': 'value.items'}
p90_conf = {'uniq_key': 'link'}
p87_conf = {
    'combine': 'or',
    'mode': 'block',
    'rule': [{'field': 'title', 'value': 'php', 'op': 'contains'}]}

p101_conf = {'rule': [{'sort_key': 'pubDate', 'sort_dir': 'desc'}]}


def pipe_gigs(test=False):
    output = (SyncPipe('fetchdata', conf=p68_conf, test=test)
        .uniq(conf=p90_conf)
        .filter(conf=p87_conf)
        .sort(conf=p101_conf)
        .list)

    for i in output:
        pprint(i)

    return output


@inlineCallbacks
def asyncPipeGigs(reactor, test=False):
    output = yield (AsyncPipe('fetchdata', conf=p68_conf, test=test)
        .uniq(conf=p90_conf)
        .filter(conf=p87_conf)
        .sort(conf=p101_conf)
        .output)

    for i in output:
        pprint(i)
