from __future__ import (
    absolute_import, division, print_function, unicode_literals)

from riko import modules as mod
from riko.lib.collections import SyncPipe


def pipe_679e2c544332e978b15b6b163767975f(**kwargs):
    p232_conf = {
        'attrs': [
            {'value': 'www.google.com', 'key': 'link'},
            {'value': 'google', 'key': 'title'},
            {'value': '$', 'key': 'author'}]}

    p421_conf = {'rule': [{'find': '$', 'param': 'first', 'replace': 'USD'}]}

    p421 = (
        SyncPipe('itembuilder', conf=p232_conf, **kwargs)
            .strreplace(conf=p421_conf, field='author', **kwargs)
            .output)

    return p421

if __name__ == "__main__":
    for i in pipe_679e2c544332e978b15b6b163767975f():
        print(i)
