# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab

"""Twisted utility functions"""

from twisted.internet import defer
from twisted.internet.defer import maybeDeferred, gatherResults
from functools import partial
from itertools import ifilter, imap, tee, izip, starmap
from pipe2py.lib import utils

asyncNone = defer.succeed(None)
asyncReturn = lambda result: defer.succeed(result)


def trueDeferreds(sources, filter_func=None):
    return imap(partial(maybeDeferred, ifilter, filter_func), sources)


def asyncImap(asyncCallable, *args):
    deferreds = imap(asyncCallable, *args)
    # coop = repeat(coiterate(deferreds), workers)
    return gatherResults(deferreds, consumeErrors=True)


def asyncStarMap(asyncCallable, iterable):
    deferreds = starmap(asyncCallable, iterable)
    return gatherResults(deferreds, consumeErrors=True)


def asyncImapFunc(funcs, items):
    return asyncStarMap(utils.star_func, izip(items, funcs))


def asyncBroadcast(_INPUT, *funcs):
    splits = izip(*tee(_INPUT, len(funcs)))
    return asyncImap(partial(asyncImapFunc, funcs), splits)


def asyncDispatch(splits, *funcs):
    return asyncImap(partial(asyncImapFunc, funcs), splits)


def asyncGather(splits, asyncCallable):
    func = lambda split: asyncCallable(*list(split))
    return asyncImap(partial(func, asyncCallable), splits)
