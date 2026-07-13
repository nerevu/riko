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

import itertools as it
from functools import partial

from . import coroutine, reactor, return_value
from .mock import FakeReactor

try:
    from twisted.internet.task import Cooperator
except ImportError:
    Cooperator = real_task = gatherResults = None
else:
    from twisted.internet import task as real_task
    from twisted.internet.defer import gatherResults


def get_task():
    if reactor.fake:
        task = Cooperator(
            scheduler=partial(FakeReactor().callLater, FakeReactor._DELAY)
        )
    else:
        task = real_task.Cooperator()

    return task


@coroutine
def coop_reduce(func, iterable, initializer=None):
    task = get_task()
    iterable = iter(iterable)
    x = initializer or next(iterable)
    result = {}

    def work(func, it, x):
        for y in it:
            result["value"] = x = func(x, y)
            yield

    _task = task.cooperate(work(func, iterable, x))
    yield _task.whenDone()
    return_value(result["value"])


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
def async_map(afunc, iterable, connections=0, **kwargs):
    """
    Parallel map for deferred callables using cooperative multitasking
    http://stackoverflow.com/a/20376166/408556
    """
    if connections and not reactor.fake:
        results = []
        work = (afunc(x, **kwargs).addCallback(results.append) for x in iterable)
        deferreds = [get_task().coiterate(work) for _ in range(connections)]
        yield gatherResults(deferreds, consumeErrors=True)
    else:
        afunc = partial(afunc, **kwargs)
        deferreds = map(afunc, iterable)
        results = yield gatherResults(deferreds, consumeErrors=True)

    return_value(results)


def async_starmap(async_func, iterable):
    """itertools.starmap for deferred callables"""
    deferreds = it.starmap(async_func, iterable)
    return gatherResults(deferreds, consumeErrors=True)


def async_dispatch(split, *async_funcs, **kwargs):
    return async_starmap(lambda item, f: f(item), zip(split, async_funcs))


def async_broadcast(item, *async_funcs, **kwargs):
    return async_dispatch(it.repeat(item), *async_funcs, **kwargs)
