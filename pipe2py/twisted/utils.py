# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab

"""Twisted utility functions"""

from __future__ import (
    absolute_import, division, print_function, with_statement,
    unicode_literals)

import itertools as it

from os import environ
from sys import executable
from functools import partial

from twisted.internet import defer
from twisted.internet.defer import (
    inlineCallbacks, maybeDeferred, gatherResults, returnValue)
from twisted.internet.task import coiterate, cooperate
from twisted.internet.utils import getProcessOutput
from pipe2py.lib import utils
from pipe2py.lib.log import Logger

logger = Logger(__name__).logger

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
def coop(asyncCallable, callback, *iterables):
    work = _get_work(asyncCallable, callback, it.imap, *iterables)
    return coiterate(work)


def asyncParallel(asyncCallable, callback, *iterables):
    work = _get_work(asyncCallable, callback, it.imap, *iterables)
    return _parallel(work, asyncCallable)


def coopStar(asyncCallable, callback, iterable):
    work = _get_work(asyncCallable, callback, it.starmap, *[iterable])
    return coiterate(work)


def asyncStarParallel(asyncCallable, callback, iterable):
    work = _get_work(asyncCallable, callback, it.starmap, *[iterable])
    return _parallel(work, asyncCallable)


# End user functions
def deferToProcess(source, function, *args, **kwargs):
    command = "from %s import %s\n%s(*%s, **%s)" % (
        source, function, function, args, kwargs)

    return getProcessOutput(executable, ['-c', command], environ)


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


@inlineCallbacks
def asyncCmap(asyncCallable, *iterables):
    """itertools.imap for deferred callables using cooperative multitasking
    """
    results = []
    yield coop(asyncCallable, results.append, *iterables)
    returnValue(results)


@inlineCallbacks
def asyncPmap(asyncCallable, *iterables):
    """itertools.imap for deferred callables using parallel cooperative
    multitasking
    """
    results = []
    yield asyncParallel(asyncCallable, results.append, *iterables)
    returnValue(results)


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


def asyncDispatch(split, *asyncCallables, **kwargs):
    return asyncStarMap(lambda item, f: f(item), it.izip(split, asyncCallables))


def asyncBroadcast(item, *asyncCallables, **kwargs):
    return asyncDispatch(it.repeat(item), *asyncCallables, **kwargs)
