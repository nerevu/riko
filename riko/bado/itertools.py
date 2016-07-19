# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.bado.itertools
~~~~~~~~~~~~~~~~~~~
Provides asynchronous ports of various builtin itertools functions

Examples:
    basic usage::

        >>> from riko import get_path
        >>> from riko.bado.itertools import coop_reduce
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
    from twisted.internet import task as real_task
    from twisted.internet.defer import gatherResults


def get_task():
    if reactor.fake:
        task = Cooperator(scheduler=FakeReactor().callLater)
    else:
        task = real_task

    return task


def cleanup(task):
    if task._delayedCall:
        task._delayedCall.cancel()
        task._delayedCall = None


@coroutine
def coop_reduce(func, iterable, initializer=None):
    task = get_task()
    iterable = iter(iterable)
    x = initializer or next(iterable)
    result = {}

    def work(func, it, x):
        for y in it:
            result['value'] = x = func(x, y)
            yield

    _task = task.cooperate(work(func, iterable, x))
    yield _task.whenDone()
    cleanup(task) if reactor.fake else None
    return_value(result['value'])


def async_reduce(async_func, iterable, initializer=None):
    it = iter(iterable)
    x = initializer or next(it)

    @coroutine
    def work(async_func, it, x):
        for y in it:
            x = yield async_func(x, y)

        return_value(x)

    return work(async_func, it, x)


@coroutine
def async_map(async_func, iterable, connections=0):
    """parallel map for deferred callables using cooperative multitasking
    http://stackoverflow.com/a/20376166/408556
    """
    if connections and not reactor.fake:
        results = []
        work = (async_func(x).addCallback(results.append) for x in iterable)
        deferreds = [get_task().coiterate(work) for _ in range(connections)]
        yield gatherResults(deferreds, consumeErrors=True)
    else:
        deferreds = map(async_func, iterable)
        results = yield gatherResults(deferreds, consumeErrors=True)

    return_value(results)


def async_starmap(async_func, iterable):
    """itertools.starmap for deferred callables
    """
    deferreds = it.starmap(async_func, iterable)
    return gatherResults(deferreds, consumeErrors=True)


def async_dispatch(split, *async_funcs, **kwargs):
    return async_starmap(lambda item, f: f(item), zip(split, async_funcs))


def async_broadcast(item, *async_funcs, **kwargs):
    return async_dispatch(it.repeat(item), *async_funcs, **kwargs)
