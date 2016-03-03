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
from StringIO import StringIO

from twisted.internet import defer
from twisted.internet.defer import (
    inlineCallbacks, maybeDeferred, gatherResults, returnValue)
from twisted.internet.task import Cooperator
from twisted.internet.utils import getProcessOutput
from twisted.protocols.basic import FileSender
from twisted.web.client import getPage
from twisted.test.proto_helpers import AccumulatingProtocol, StringTransport
from pipe2py.lib import utils
from pipe2py.lib.log import Logger

logger = Logger(__name__).logger

WORKERS = 50

asyncNone = defer.succeed(None)
asyncReturn = partial(defer.succeed)
urlRead = lambda url: getPage(url) if url.startswith('http') else readFile(url, StringTransport())
asyncPartial = lambda f, **kwargs: partial(maybeDeferred, f, **kwargs)


# http://stackoverflow.com/q/26314586/408556
# http://stackoverflow.com/q/8157197/408556
# http://stackoverflow.com/a/33708936/408556
class FileReader(AccumulatingProtocol):
    def __init__(self, filename, transform=None):
        self.f = open(filename, 'rb')
        self.transform = transform
        self.producer = FileSender()

    def cleanup(self, *args):
        self.f.close()
        self.producer.stopProducing()

    def connectionLost(self, reason):
        logger.debug('connectionLost: %s', reason)
        self.cleanup()

    def connectionMade(self):
        logger.debug('Connection made from %s', self.transport.getPeer())
        args = (self.f, self.transport, self.transform)
        self.d = self.closedDeferred = self.producer.beginFileTransfer(*args)

        while not self.d.called:
            self.producer.resumeProducing()

        self.d.addErrback(logger.error)
        self.d.addBoth(self.cleanup)


class FakeDelayedCall(object):
    """
    Fake delayed call which lets us simulate the scheduler.
    """
    def __init__(self, func):
        """
        A function to run, later.
        """
        logger.debug('FakeDelayedCall')
        self.func = func
        self.cancelled = False

    def cancel(self):
        """
        Don't run my function later.
        """
        self.cancelled = True


class FakeScheduler(object):
    """
    A fake scheduler for testing against.
    """
    def __init__(self):
        """
        Create a fake scheduler with a list of work to do.
        """
        logger.debug('FakeScheduler')
        self.work = []

    def __call__(self, thunk):
        """
        Schedule a unit of work to be done later.
        """
        logger.debug('call')
        unit = FakeDelayedCall(thunk)
        self.work.append(unit)
        return unit

    def pump(self):
        """
        Do all of the work that is currently available to be done.
        """
        logger.debug('pump')
        work, self.work = self.work, []

        for unit in work:
            if not unit.cancelled:
                unit.func()

scheduler=FakeScheduler()
cooperator = Cooperator(scheduler=scheduler, terminationPredicateFactory=lambda: lambda: True)
coiterate, cooperate = cooperator.coiterate, cooperator.cooperate


@inlineCallbacks
def readFile(filename, transport, protocol=FileReader):
    proto = protocol(filename.replace('file://', ''))
    proto.makeConnection(transport)
    yield proto.d
    # returnValue(proto.data)
    returnValue(proto.transport.value())


@inlineCallbacks
def getFile(filename, transport, protocol=FileReader):
    proto = protocol(filename.replace('file://', ''))
    proto.makeConnection(transport)
    yield proto.d
    proto.transport.io.seek(0)
    returnValue(proto.transport.io)


@inlineCallbacks
def urlOpen(url):
    if url.startswith('http'):
        f = StringIO()
        yield downloadPage(url, f)
        f.seek(0)
    else:
        f = yield getFile(url, StringTransport())

    returnValue(f)


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
    results = []

    def work(func, it, x):
        for y in it:
            x = func(x, y)
            results.append(x)
            yield None

    task = cooperate(work(func, it, x))
    d = task.whenDone()

    while cooperator._tasks:
        task._cooperator._scheduler.pump()

    yield d
    returnValue(results.pop())


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
