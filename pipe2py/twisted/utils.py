# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab

"""Twisted utility functions"""

from __future__ import (
    absolute_import, division, print_function, with_statement,
    unicode_literals)

import itertools as it

from functools import partial
from twisted.internet import defer
from twisted.internet.defer import (
    inlineCallbacks, maybeDeferred, gatherResults, returnValue)
from twisted.internet.task import coiterate, cooperate
from functools import partial
from itertools import ifilter, imap, starmap, repeat
from twisted.internet.protocol import ProcessProtocol
from twisted.internet.reactor import spawnProcess
from pipe2py.lib import utils

WORKERS = 50

asyncNone = defer.succeed(None)
asyncReturn = partial(defer.succeed)


def _get_work(asyncCallable, callback, map_func, *iterables):
    func = lambda *args: asyncCallable(*args).addCallback(callback)
    return map_func(func, *iterables)


def _parallel(work, asyncCallable):
    deferreds = it.repeat(coiterate(work), WORKERS)
    return gatherResults(deferreds, consumeErrors=True)


# helper functions
# def coop(asyncCallable, callback, *iterables):
#     work = _get_work(asyncCallable, callback, it.imap, *iterables)
#     return coiterate(work)


# def asyncParallel(asyncCallable, callback, *iterables):
#     work = _get_work(asyncCallable, callback, it.imap, *iterables)
#     return _parallel(work, asyncCallable)


def coopStar(asyncCallable, callback, iterable):
    work = _get_work(asyncCallable, callback, it.starmap, *[iterable])
    return coiterate(work)


def asyncStarParallel(asyncCallable, callback, iterable):
    work = _get_work(asyncCallable, callback, it.starmap, *[iterable])
    return _parallel(work, asyncCallable)


def trueDeferreds(sources, filter_func=None):
    return it.imap(partial(maybeDeferred, it.ifilter, filter_func), sources)


@inlineCallbacks
def coopReduce(func, iterable, initializer=None):
    it = iter(iterable)
    x = initializer or next(it)

    def cooperator(func, it, x):
        for y in it:
            x = func(x, y)
            yield

        returnValue(x)

    task = cooperate(cooperator(func, it, x))
    result = yield task.whenDone()
    returnValue(result)


def asyncReduce(asyncCallable, iterable, initializer=None):
    it = iter(iterable)
    x = initializer or next(it)

    @inlineCallbacks
    def work(asyncCallable, it, x):
        for y in it:
            x = yield asyncCallable(x, y)

        returnValue(x)

    return work(asyncCallable, it, x)


def asyncImap(asyncCallable, *iterables):
    """itertools.imap for deferred callables
    """
    deferreds = it.imap(asyncCallable, *iterables)
    return gatherResults(deferreds, consumeErrors=True)


@inlineCallbacks
def asyncStarCmap(asyncCallable, iterable):
    """itertools.starmap for deferred callables using cooperative multitasking
    """
    results = []
    yield coopStar(asyncCallable, results.append, iterable)
    returnValue(results)


@inlineCallbacks
def asyncStarPmap(asyncCallable, iterable):
    """itertools.starmap for deferred callables using parallel cooperative
    multitasking
    """
    results = []
    yield asyncStarParallel(asyncCallable, results.append, iterable)
    returnValue(results)


def asyncStarMap(asyncCallable, iterable):
    """itertools.starmap for deferred callables
    """
    deferreds = it.starmap(asyncCallable, iterable)
    return gatherResults(deferreds, consumeErrors=True)


# Internal functions
_apply_func = partial(utils._apply_func, map_func=asyncStarMap)
_map_func = asyncImap


def asyncBroadcast(_INPUT, *asyncCallables):
    """copies a source and delivers the items to multiple functions

    _INPUT = it.repeat({'title': 'foo'}, 3)

           /--> foo2bar(_INPUT) --> _OUTPUT1 == it.repeat('bar', 3)
          /
    _INPUT ---> foo2baz(_INPUT) --> _OUTPUT2 == it.repeat('baz', 3)
          \
           \--> foo2qux(_INPUT) --> _OUTPUT3 == it.repeat('quz', 3)

    The way you would construct such a flow in code would be::

        succeed = twisted.internet.defer.succeed
        foo2bar = lambda item: succeed(item['title'].replace('foo', 'bar'))
        foo2baz = lambda item: succeed(item['title'].replace('foo', 'baz'))
        foo2qux = lambda item: succeed(item['title'].replace('foo', 'quz'))
        asyncBroadcast(_INPUT, foo2bar, foo2baz, foo2qux)
    """
    kwargs = {'map_func': _map_func, 'apply_func': _apply_func}
    return utils.broadcast(_INPUT, *asyncCallables, **kwargs)


def asyncDispatch(splits, *asyncCallables):
    """takes multiple sources (returned by asyncDispatch or asyncBroadcast)
    and delivers the items to multiple functions

    _INPUT1 = it.repeat('bar', 3)
    _INPUT2 = it.repeat('baz', 3)
    _INPUT3 = it.repeat('qux', 3)

    _INPUT1 --> double(_INPUT) --> _OUTPUT1 == it.repeat('barbar', 3)

    _INPUT2 --> triple(_INPUT) --> _OUTPUT2 == it.repeat('bazbazbaz', 3)

    _INPUT3 --> quadruple(_INPUT) --> _OUTPUT3 == it.repeat('quxquxquxqux', 3)

    The way you would construct such a flow in code would be::

        succeed = twisted.internet.defer.succeed
        _INPUT = it.repeat({'title': 'foo'}, 3)
        splits = asyncBroadcast(_INPUT, foo2bar, foo2baz, foo2qux)
        double = lambda item: succeed(item * 2)
        triple = lambda item: succeed(item * 3)
        quadruple = lambda item: succeed(item * 4)
        asyncBroadcast(splits, double, triple, quadruple)
    """
    kwargs = {'map_func': _map_func, 'apply_func': _apply_func}
    return utils.dispatch(splits, *asyncCallables, **kwargs)
