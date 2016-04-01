# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab

"""Twisted utility functions"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

import itertools as it

from os import environ
from sys import executable
from functools import partial
from io import StringIO
from html.entities import entitydefs, name2codepoint

from builtins import *
from zope.interface import implementer
from twisted.internet import defer
from twisted.internet.defer import (
    inlineCallbacks, maybeDeferred, gatherResults, returnValue, Deferred)
from twisted.internet.task import (
    Cooperator, coiterate as _coiterate, cooperate as _cooperate)
from twisted.internet.utils import getProcessOutput
from twisted.internet.interfaces import IReactorCore
from twisted.internet.reactor import callLater
from twisted.protocols.basic import FileSender
from twisted.web.client import getPage, downloadPage
from twisted.web.microdom import EntityReference
from twisted.test.proto_helpers import (
    MemoryReactor, AccumulatingProtocol, StringTransport)

from riko.lib.log import Logger
from riko.lib.utils import _make_content

logger = Logger(__name__).logger

asyncNone = defer.succeed(None)
asyncReturn = partial(defer.succeed)
asyncPartial = lambda f, **kwargs: partial(maybeDeferred, f, **kwargs)

global FAKE_REACTOR
FAKE_REACTOR = False


# http://stackoverflow.com/q/26314586/408556
# http://stackoverflow.com/q/8157197/408556
# http://stackoverflow.com/a/33708936/408556
class FileReader(AccumulatingProtocol):
    def __init__(self, filename, transform=None, delay=0):
        self.f = open(filename, 'rb')
        self.transform = transform
        self.delay = delay
        self.producer = FileSender()

    def cleanup(self, *args):
        self.f.close()
        self.producer.stopProducing()

    def resumeProducing(self):
        chunk = ''
        if self.file:
            chunk = self.file.read(self.CHUNK_SIZE)

        if not chunk:
            self.file = None
            self.consumer.unregisterProducer()

            if self.deferred and self.delay:
                callLater(seconds, self.deferred.callback, self.lastSent)
            elif self.deferred:
                self.deferred.callback(self.lastSent)

            self.deferred = None
            return

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
    """Fake delayed call which lets us simulate the scheduler.
    """
    def __init__(self, func):
        """A function to run, later.
        """
        self.func = func
        self.cancelled = False

    def cancel(self):
        """Don't run my function later.
        """
        self.cancelled = True


@implementer(IReactorCore)
class FakeReactor(MemoryReactor):
    """A fake reactor to be used in tests.  This reactor doesn't actually do
    much that's useful yet.  It accepts TCP connection setup attempts, but
    they will never succeed.

    Examples:
        >>> import sys
        >>> from twisted.internet.abstract import FileDescriptor
        >>> from twisted.internet.fdesc import readFromFD, setNonBlocking
        >>>
        >>> # reactor = proto_helpers.FakeReactor()
        >>> reactor = FakeReactor()
        >>> f = FileDescriptor(reactor)
        >>> f.fileno = sys.__stdout__.fileno
        >>> fd = f.fileno()
        >>> setNonBlocking(fd)
        >>> readFromFD(fd, print)
    """
    def __init__(self):
        super(FakeReactor, self).__init__()
        global FAKE_REACTOR
        FAKE_REACTOR = True
        self.work = []
        self.running = False

    def resolve(self, *args, **kw):
        """Return a L{twisted.internet.defer.Deferred} that will resolve a hostname.
        """
        pass

    def run(self):
        """Fake L{IReactorCore.run}.
        """
        self.running = True

    def stop(self):
        """Fake L{IReactorCore.stop}.
        """
        self.running = False

    def crash(self):
        """Fake L{IReactorCore.crash}.
        """
        self.running = False

    def iterate(self, *args, **kw):
        """Fake L{IReactorCore.iterate}.
        """
        pass

    def fireSystemEvent(self, *args, **kw):
        """Fake L{IReactorCore.fireSystemEvent}.
        """
        pass

    def addSystemEventTrigger(self, *args, **kw):
        """Fake L{IReactorCore.addSystemEventTrigger}.
        """
        pass

    def removeSystemEventTrigger(self, *args, **kw):
        """Fake L{IReactorCore.removeSystemEventTrigger}.
        """
        pass

    def callWhenRunning(self, *args, **kw):
        """Fake L{IReactorCore.callWhenRunning}.
        """
        pass

    def getDelayedCalls(self):
        """Return all the outstanding delayed calls in the system.
        """
        return (x for x in self.work if not x.cancelled)

    def callLater(self, func):
        """Schedule a unit of work to be done later.
        """
        unit = FakeDelayedCall(func)
        self.work = it.chain(self.work, [unit])
        self.pump()
        return unit

    def pump(self):
        """Perform scheduled work
        """
        for unit in self.getDelayedCalls():
            try:
                unit.func()
            except Exception as e:
                logger.error(e)

        return

cooperator = Cooperator(scheduler=FakeReactor().callLater)


def cleanup(*args):
    if FAKE_REACTOR and cooperator._delayedCall:
        cooperator._delayedCall.cancel()
        cooperator._delayedCall = None


def asyncSleep(seconds):
    d = Deferred()
    callLater(seconds, d.callback, None)
    return d


@inlineCallbacks
def readFile(filename, transport, protocol=FileReader, **kwargs):
    proto = protocol(filename.replace('file://', ''), **kwargs)
    proto.makeConnection(transport)
    yield proto.d
    # returnValue(proto.data)
    returnValue(proto.transport.value())


@inlineCallbacks
def getFile(filename, transport, protocol=FileReader, **kwargs):
    proto = protocol(filename.replace('file://', ''), **kwargs)
    proto.makeConnection(transport)
    yield proto.d
    proto.transport.io.seek(0)
    returnValue(proto.transport.io)


@inlineCallbacks
def urlOpen(url, timeout=0, **kwargs):
    if url.startswith('http'):
        f = StringIO()
        yield downloadPage(url, f, timeout=timeout)
        f.seek(0)
    else:
        f = yield getFile(url, StringTransport(), **kwargs)

    returnValue(f)


def urlRead(url, timeout=0, **kwargs):
    if url.startswith('http'):
        content = getPage(url, timeout=timeout)
    else:
        content = readFile(url, StringTransport(), **kwargs)

    return content


def deferToProcess(source, function, *args, **kwargs):
    command = "from %s import %s\n%s(*%s, **%s)" % (
        source, function, function, args, kwargs)

    return getProcessOutput(executable, ['-c', command], environ)


@inlineCallbacks
def coopReduce(func, iterable, initializer=None):
    cooperate = cooperator.cooperate if FAKE_REACTOR else _cooperate
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
    returnValue(result['value'])


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
def pMap(func, iterable, workers=1):
    """map for synchronous callables using parallel cooperative
    multitasking
    """
    coiterate = cooperator.coiterate if FAKE_REACTOR else _coiterate
    results = []

    def work():
        for x in iterable:
            results.append(func(x))
            yield

    deferreds = it.repeat(coiterate(work()), workers)
    yield gatherResults(deferreds, consumeErrors=True)
    cleanup()
    returnValue(results)


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


def def2unicode(entitydef):
    """Convert an HTML entity reference into unicode.
    """
    def2name = {v: k for k, v in entitydefs.items()}
    name = def2name[entitydef]
    cp = name2codepoint[name]
    return chr(cp)


def elementToDict(element, tag='content'):
    """Convert a microdom element into a dict imitating how Yahoo Pipes does it.

    TODO: checkout twisted.words.xish
    """
    i = dict(element.attributes) if hasattr(element, 'attributes') else {}
    value = element.nodeValue if hasattr(element, 'nodeValue') else None

    if isinstance(element, EntityReference):
        value = def2unicode(value)

    i.update(_make_content(i, value, tag))

    for child in element.childNodes:
        tag = child.tagName if hasattr(child, 'tagName') else 'content'
        value = elementToDict(child, tag)

        # try to join the content first since microdom likes to split up
        # elements that contain a mix of text and entity reference
        try:
            i.update(_make_content(i, value, tag, append=False))
        except TypeError:
            i.update(_make_content(i, value, tag))

    if ('content' in i) and not set(i).difference(['content']):
        # element is leaf node and doesn't have attributes
        i = i['content']

    return i
