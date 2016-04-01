from __future__ import (
    absolute_import, division, print_function, unicode_literals)

from pprint import pprint
from twisted.internet.defer import inlineCallbacks
from riko.lib.collections import SyncPipe
from riko.twisted.collections import AsyncPipe

p120_conf = {'type': 'text'}
p120_inputs = {'format': '%B %d, %Y'}
p112_conf = {'type': 'date', 'default': '5/4/82', 'prompt': 'enter a date'}
p151_conf = {'format': {'terminal': 'format', 'path': 'format'}}
p100_conf = {
    'attrs': {
        'value': {'terminal': 'value', 'path': 'dateformat'}, 'key': 'date'}}

p120_kwargs = {'conf': p120_conf, 'inputs': p120_inputs, 'assign': 'format'}


def pipe_wired(test=False):
    p120 = SyncPipe('input', test=test, **p120_kwargs).output
    p151 = (SyncPipe('input', conf=p112_conf, test=test)
        .dateformat(conf=p151_conf, format=p120)
        .output)

    output = (SyncPipe('itembuilder', conf=p100_conf, value=p151, test=test)
        .list)

    for i in output:
        pprint(i)

    return output


@inlineCallbacks
def asyncPipeWired(reactor, test=False):
    p120 = yield AsyncPipe('input', test=test, **p120_kwargs).output
    p151 = yield (AsyncPipe('input', conf=p112_conf, test=test)
        .dateformat(conf=p151_conf, format=p120)
        .output)

    output_kwargs = {'conf': p100_conf, 'value': p151, 'test': test}
    output = yield (AsyncPipe('itembuilder', **output_kwargs)
        .list)

    for i in output:
        pprint(i)
