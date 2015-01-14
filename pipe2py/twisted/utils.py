# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab

"""Twisted utility functions"""

from twisted.internet import defer
from twisted.internet.defer import (
    inlineCallbacks, maybeDeferred, gatherResults, returnValue)
from functools import partial
from itertools import ifilter, imap, tee, izip, starmap
from pipe2py.lib import utils
from pipe2py.lib.dotdict import DotDict

asyncNone = defer.succeed(None)
asyncReturn = lambda result: defer.succeed(result)


def trueDeferreds(sources, filter_func=None):
    return imap(partial(maybeDeferred, ifilter, filter_func), sources)


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
    x = next(it) if initializer is None else initializer

    @inlineCallbacks
    def work(asyncCallable, it, x):
        for y in it:
            x = yield asyncCallable(x, y)

        returnValue(x)

    return work(asyncCallable, it, x)


def asyncImap(asyncCallable, *iterables):
    """itertools.imap for deferred callables
    """
    deferreds = imap(asyncCallable, *iterables)
    return gatherResults(deferreds, consumeErrors=True)


def asyncStarMap(asyncCallable, iterable):
    deferreds = starmap(asyncCallable, iterable)
    return gatherResults(deferreds, consumeErrors=True)


# Internal functions
_apply_func = partial(utils._apply_func, map_func=asyncStarMap)
_map_func = asyncImap


def asyncBroadcast(_INPUT, *asyncCallables):
    kwargs = {'map_func': _map_func, 'apply_func': _apply_func}
    return utils.broadcast(_INPUT, *asyncCallables, **kwargs)


def asyncDispatch(splits, *asyncCallables):
    kwargs = {'map_func': _map_func, 'apply_func': _apply_func}
    return utils.dispatch(splits, *asyncCallables, **kwargs)
