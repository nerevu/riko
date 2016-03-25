from __future__ import (
    absolute_import, division, print_function, unicode_literals)

from pprint import pprint
from twisted.internet.defer import inlineCallbacks
from riko.lib.collections import SyncPipe, SyncCollection
from riko.twisted.collections import AsyncPipe, AsyncCollection

p385_conf = {'type': 'date'}
p385_inputs = {'content': '12/2/2014'}
p405_conf = {'format': '%B %d, %Y'}
p393_conf = {
    'attrs': [
        {'value': {'terminal': 'date', 'path': 'dateformat'}, 'key': 'date'},
        {'value': {'terminal': 'year', 'path': 'year'}, 'key': 'year'}]}


def pipe_split(test=False):
    p405, p406 = (SyncPipe('input', conf=p385_conf, inputs=p385_inputs, test=test)
        .dateformat(conf=p405_conf)
        .split()
        .output)

    output = (SyncPipe('itembuilder', conf=p393_conf, date=p405, year=p406, test=test)
        .list)

    for i in output:
        pprint(i)

    return output


@inlineCallbacks
def asyncPipeSplit(reactor, test=False):
    p405, p406 = yield (AsyncPipe('input', conf=p385_conf, inputs=p385_inputs, test=test)
        .dateformat(conf=p405_conf)
        .split()
        .output)

    output = yield (AsyncPipe('itembuilder', conf=p393_conf, date=p405, year=p406, test=test)
        .list)

    for i in output:
        pprint(i)
