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


# Internal functions
_apply_func = partial(utils._apply_func, map_func=asyncStarMap)
_map_func = asyncImap


def asyncBroadcast(_INPUT, *asyncCallables):
    kwargs = {'map_func': _map_func, 'apply_func': _apply_func}
    return utils.broadcast(_INPUT, *asyncCallables, **kwargs)


def asyncDispatch(splits, *asyncCallables):
    kwargs = {'map_func': _map_func, 'apply_func': _apply_func}
    return utils.dispatch(splits, *asyncCallables, **kwargs)


def asyncGather(splits, asyncCallable):
    return utils.gather(splits, asyncCallable, map_func=_map_func)
