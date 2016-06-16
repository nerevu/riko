# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.bado.itertools
~~~~~~~~~~~~~~~~~~~
Provides asynchronous ports of various builtin itertools functions

Examples:
    basic usage::

        >>> from riko import get_path
        >>> from riko.bado.itertools import coopReduce
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

import itertools as it

from builtins import *
from . import coroutine, return_value, reactor
from .mock import FakeReactor

try:
    from twisted.internet.task import Cooperator
except ImportError:
    pass
else:
    from twisted.internet.defer import gatherResults
    from twisted.internet.task import (
        coiterate as _coiterate, cooperate as _cooperate)

    cooperator = Cooperator(scheduler=FakeReactor().callLater)


def cleanup(*args):
    if reactor.fake and cooperator._delayedCall:
        cooperator._delayedCall.cancel()
        cooperator._delayedCall = None


@coroutine
def coopReduce(func, iterable, initializer=None):
    cooperate = cooperator.cooperate if reactor.fake else _cooperate
    iterable = iter(iterable)
    x = initializer or next(iterable)
    result = {}

    def work(func, it, x):
        for y in it:
            result['value'] = x = func(x, y)
            yield

    task = cooperate(work(func, iterable, x))
    yield task.whenDone()
    cleanup()
    return_value(result['value'])


def asyncReduce(asyncCallable, iterable, initializer=None):
    it = iter(iterable)
    x = initializer or next(it)

    @coroutine
    def work(asyncCallable, it, x):
        for y in it:
            x = yield asyncCallable(x, y)

        return_value(x)

    return work(asyncCallable, it, x)


@coroutine
def pMap(func, iterable, workers=1):
    """map for synchronous callables using parallel cooperative
    multitasking
    """
    coiterate = cooperator.coiterate if reactor.fake else _coiterate
    results = []

    def work():
        for x in iterable:
            results.append(func(x))
            yield

    deferreds = it.repeat(coiterate(work()), workers)
    yield gatherResults(deferreds, consumeErrors=True)
    cleanup()
    return_value(results)


def asyncImap(asyncCallable, *iterables):
    """map for deferred callables
    """
    deferreds = map(asyncCallable, *iterables)
    return gatherResults(deferreds, consumeErrors=True)


def asyncStarMap(asyncCallable, iterable):
    """itertools.starmap for deferred callables
    """
    deferreds = it.starmap(asyncCallable, iterable)
    return gatherResults(deferreds, consumeErrors=True)


def asyncDispatch(split, *asyncCallables, **kwargs):
    return asyncStarMap(lambda item, f: f(item), zip(split, asyncCallables))


def asyncBroadcast(item, *asyncCallables, **kwargs):
    return asyncDispatch(it.repeat(item), *asyncCallables, **kwargs)
