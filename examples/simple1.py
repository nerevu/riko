from __future__ import (
    absolute_import, division, print_function, unicode_literals)

from pprint import pprint
from twisted.internet.defer import inlineCallbacks
from riko.lib.collections import SyncPipe
from riko.twisted.collections import AsyncPipe

p1_conf = {
    'attrs': [
        {
            'value': 'http://www.caltrain.com/Fares/farechart.html',
            'key': 'url'}]}

p2_conf = {
    'rule': {
        'field': 'url', 'match': {'subkey': 'url'}, 'replace': 'farechart'}}


def pipe(test=False):
    stream = (SyncPipe('itembuilder', conf=p1_conf, test=test)
        .regex(conf=p2_conf)
        .list)

    for i in stream:
        pprint(i)

    return stream


@inlineCallbacks
def asyncPipe(reactor, test=False):
    stream = yield (AsyncPipe('itembuilder', conf=p1_conf, test=test)
        .regex(conf=p2_conf)
        .list)

    for i in stream:
        pprint(i)
