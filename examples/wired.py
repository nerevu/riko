from __future__ import (
    absolute_import, division, print_function, unicode_literals)

from pprint import pprint
from riko.bado import coroutine
from riko.collections import SyncPipe, AsyncPipe

p120_conf = {'type': 'text'}
p120_inputs = {'format': '%B %d, %Y'}
p112_conf = {'type': 'date', 'default': '5/4/82', 'prompt': 'enter a date'}
p151_conf = {'format': {'terminal': 'format', 'path': 'format'}}
p100_conf = {
    'attrs': {
        'value': {'terminal': 'value', 'path': 'dateformat'}, 'key': 'date'}}

p120_kwargs = {'conf': p120_conf, 'inputs': p120_inputs, 'assign': 'format'}


def pipe(test=False):
    s1 = SyncPipe('input', test=test, **p120_kwargs).output
    s2 = (SyncPipe('input', conf=p112_conf, test=test)
        .dateformat(conf=p151_conf, format=s1)
        .output)

    stream = (SyncPipe('itembuilder', conf=p100_conf, value=s2, test=test)
        .list)

    for i in stream:
        pprint(i)

    return stream


@coroutine
def async_pipe(reactor, test=False):
    s1 = yield AsyncPipe('input', test=test, **p120_kwargs).output
    s2 = yield (AsyncPipe('input', conf=p112_conf, test=test)
        .dateformat(conf=p151_conf, format=s1)
        .output)

    output_kwargs = {'conf': p100_conf, 'value': s2, 'test': test}
    output = yield (AsyncPipe('itembuilder', **output_kwargs)
        .list)

    for i in output:
        pprint(i)
