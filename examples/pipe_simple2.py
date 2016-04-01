from __future__ import (
    absolute_import, division, print_function, unicode_literals)

from pprint import pprint
from twisted.internet.defer import inlineCallbacks
from riko.lib.collections import SyncPipe
from riko.twisted.collections import AsyncPipe

p232_conf = {
    'attrs': [
        {'value': 'www.google.com', 'key': 'link'},
        {'value': 'google', 'key': 'title'},
        {'value': 'empty', 'key': 'author'}]}

p421_conf = {'rule': [{'find': 'empty', 'param': 'first', 'replace': 'ABC'}]}


def pipe_simple2(test=False):
    output = (SyncPipe('itembuilder', conf=p232_conf, test=test)
        .strreplace(conf=p421_conf, field='author', assign='author')
        .list)

    for i in output:
        pprint(i)

    return output


@inlineCallbacks
def asyncPipeSimple2(reactor, test=False):
    output = yield (AsyncPipe('itembuilder', conf=p232_conf, test=test)
        .strreplace(conf=p421_conf, field='author', assign='author')
        .list)

    for i in output:
        pprint(i)
