from __future__ import (
    absolute_import, division, print_function, unicode_literals)

from pprint import pprint
from riko.bado import coroutine
from riko.collections import SyncPipe, AsyncPipe

p232_conf = {
    'attrs': [
        {'value': 'www.google.com', 'key': 'link'},
        {'value': 'google', 'key': 'title'},
        {'value': 'empty', 'key': 'author'}]}

p421_conf = {'rule': [{'find': 'empty', 'param': 'first', 'replace': 'ABC'}]}


def pipe(test=False):
    stream = (SyncPipe('itembuilder', conf=p232_conf, test=test)
        .strreplace(conf=p421_conf, field='author', assign='author')
        .list)

    for i in stream:
        pprint(i)

    return stream


@coroutine
def async_pipe(reactor, test=False):
    stream = yield (AsyncPipe('itembuilder', conf=p232_conf, test=test)
        .strreplace(conf=p421_conf, field='author', assign='author')
        .list)

    for i in stream:
        pprint(i)
