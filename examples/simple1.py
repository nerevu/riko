from __future__ import (
    absolute_import, division, print_function, unicode_literals)

from pprint import pprint
from riko.bado import coroutine
from riko.collections.sync import SyncPipe
from riko.collections.async import AsyncPipe

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
        pprint(str(i['url']))

    return stream


@coroutine
def async_pipe(reactor, test=False):
    stream = yield (AsyncPipe('itembuilder', conf=p1_conf, test=test)
        .regex(conf=p2_conf)
        .list)

    for i in stream:
        pprint(str(i['url']))
