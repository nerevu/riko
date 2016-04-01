from __future__ import (
    absolute_import, division, print_function, unicode_literals)

from pprint import pprint
from twisted.internet.defer import inlineCallbacks
from riko.lib.collections import SyncPipe
from riko.twisted.collections import AsyncPipe

p163_conf = {
    'attrs': [
        {
            'value': 'http://www.caltrain.com/Fares/farechart.html',
            'key': 'url'}]}

p134_conf = {
    'rule': {
        'field': 'url', 'match': {'subkey': 'url'}, 'replace': 'farechart'}}


def pipe_simple1(test=False):
    output = (SyncPipe('itembuilder', conf=p163_conf, test=test)
        .regex(conf=p134_conf)
        .list)

    for i in output:
        pprint(i)

    return output


@inlineCallbacks
def asyncPipeSimple1(reactor, test=False):
    output = yield (AsyncPipe('itembuilder', conf=p163_conf, test=test)
        .regex(conf=p134_conf)
        .list)

    for i in output:
        pprint(i)
