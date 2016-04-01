from __future__ import (
    absolute_import, division, print_function, unicode_literals)

from pprint import pprint
from twisted.internet.defer import inlineCallbacks
from riko.lib.collections import SyncPipe
from riko.twisted.collections import AsyncPipe

p385_conf = {'type': 'date'}
p385_in = {'content': '12/2/2014'}
p405_conf = {'format': '%B %d, %Y'}
p393_conf = {
    'attrs': [
        {'value': {'terminal': 'date', 'path': 'dateformat'}, 'key': 'date'},
        {'value': {'terminal': 'year', 'path': 'year'}, 'key': 'year'}]}

p385_kwargs = {'conf': p385_conf, 'inputs': p385_in}


def pipe_split(test=False):
    p405, p406 = (SyncPipe('input', test=test, **p385_kwargs)
        .dateformat(conf=p405_conf)
        .split()
        .output)

    p393_kwargs = {'conf': p393_conf, 'date': p405, 'year': p406, 'test': test}
    output = (SyncPipe('itembuilder', **p393_kwargs)
        .list)

    for i in output:
        pprint(i)

    return output


@inlineCallbacks
def asyncPipeSplit(reactor, test=False):
    p405, p406 = yield (AsyncPipe('input', test=test, **p385_kwargs)
        .dateformat(conf=p405_conf)
        .split()
        .output)

    p393_kwargs = {'conf': p393_conf, 'date': p405, 'year': p406, 'test': test}
    output = yield (AsyncPipe('itembuilder', **p393_kwargs)
        .list)

    for i in output:
        pprint(i)
