from __future__ import (
    absolute_import, division, print_function, unicode_literals)

from pprint import pprint
from riko.bado import coroutine
from riko.collections import SyncPipe, AsyncPipe

p385_conf = {'type': 'date'}
p385_in = {'content': '12/2/2014'}
p405_conf = {'format': '%B %d, %Y'}
p393_conf = {
    'attrs': [
        {'value': {'terminal': 'date', 'path': 'dateformat'}, 'key': 'date'},
        {'value': {'terminal': 'year', 'path': 'year'}, 'key': 'year'}]}

p385_kwargs = {'conf': p385_conf, 'inputs': p385_in}


def pipe(test=False):
    s1, s2 = (SyncPipe('input', test=test, **p385_kwargs)
        .dateformat(conf=p405_conf)
        .split()
        .output)

    p393_kwargs = {'conf': p393_conf, 'date': s1, 'year': s2, 'test': test}
    stream = SyncPipe('itembuilder', **p393_kwargs).list

    for i in stream:
        pprint(i)

    return stream


@coroutine
def async_pipe(reactor, test=False):
    s1, s2 = yield (AsyncPipe('input', test=test, **p385_kwargs)
        .dateformat(conf=p405_conf)
        .split()
        .output)

    p393_kwargs = {'conf': p393_conf, 'date': s1, 'year': s2, 'test': test}
    stream = yield AsyncPipe('itembuilder', **p393_kwargs).list

    for i in stream:
        pprint(i)
