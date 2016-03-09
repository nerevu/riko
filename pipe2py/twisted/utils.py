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
from htmlentitydefs import entitydefs, name2codepoint
from zope.interface import implementer

from twisted.internet import defer
from twisted.internet.defer import (
    inlineCallbacks, maybeDeferred, gatherResults, returnValue)
from twisted.internet.task import Cooperator, coiterate, cooperate
from twisted.internet.utils import getProcessOutput
from twisted.internet.fdesc import readFromFD, setNonBlocking
from twisted.internet.interfaces import IReactorCore
from twisted.protocols.basic import FileSender
from twisted.web.client import getPage
from twisted.test.proto_helpers import MemoryReactor, AccumulatingProtocol, StringTransport
from twisted.web.microdom import Text, EntityReference

from pipe2py.lib.log import Logger
from pipe2py.lib.utils import _make_content

logger = Logger(__name__).logger

asyncNone = defer.succeed(None)
asyncReturn = partial(defer.succeed)
urlRead = lambda url: getPage(url) if url.startswith('http') else readFile(url, StringTransport())
asyncPartial = lambda f, **kwargs: partial(maybeDeferred, f, **kwargs)

global FAKE_REACTOR
FAKE_REACTOR = False

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
        self.func = func
        self.cancelled = False

    def cancel(self):
        """
        Don't run my function later.
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
        self.work = []
        self.running = False

    def resolve(self, *args, **kw):
        """Return a L{twisted.internet.defer.Deferred} that will resolve a hostname.
        """
        pass

    def run(self):
        """Fake L{IReactorCore.run}.
        """
        global FAKE_REACTOR
        FAKE_REACTOR = True
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
def urlOpen(url, timeout=None):
    # TODO: implement timeout kwarg
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


def _parallel(work, asyncCallable, workers):
    coiterate = cooperator.coiterate if FAKE_REACTOR else coiterate
    deferreds = it.repeat(coiterate(work), workers)
    d = gatherResults(deferreds, consumeErrors=True)
    d.addCallbacks(cleanup, logger.error)
    return d


# helper functions
def coop(asyncCallable, callback, *iterables):
    coiterate = cooperator.coiterate if FAKE_REACTOR else coiterate
    work = _get_work(asyncCallable, callback, it.imap, *iterables)
    d = coiterate(work)
    d.addCallbacks(cleanup, logger.error)
    return d


def coopStar(asyncCallable, callback, iterable):
    coiterate = cooperator.coiterate if FAKE_REACTOR else coiterate
    work = _get_work(asyncCallable, callback, it.starmap, *[iterable])
    d = coiterate(work)
    d.addCallbacks(cleanup, logger.error)
    return d


def asyncParallel(asyncCallable, callback, *iterables, **kwargs):
    work = _get_work(asyncCallable, callback, it.imap, *iterables)
    return _parallel(work, asyncCallable, kwargs.get('workers', 0))


def asyncStarParallel(asyncCallable, callback, iterable, workers=0):
    work = _get_work(asyncCallable, callback, it.starmap, *[iterable])
    return _parallel(work, asyncCallable, workers)


# End user functions
def deferToProcess(source, function, *args, **kwargs):
    command = "from %s import %s\n%s(*%s, **%s)" % (
        source, function, function, args, kwargs)

    return getProcessOutput(executable, ['-c', command], environ)


@inlineCallbacks
def coopReduce(func, iterable, initializer=None):
    cooperate = cooperator.cooperate if FAKE_REACTOR else cooperate
    it = iter(iterable)
    x = initializer or next(it)
    result = {}

    def work(func, it, x):
        for y in it:
            result['value'] = x = func(x, y)
            yield

    task = cooperate(work(func, it, x))
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
@inlineCallbacks
def asyncPmap(asyncCallable, *iterables, **kwargs):
    """itertools.imap for deferred callables using parallel cooperative
    multitasking
    """
    results = []
    yield asyncParallel(asyncCallable, results.append, *iterables, **kwargs)
    returnValue(results)


@inlineCallbacks
def asyncCmap(asyncCallable, *iterables):
    """itertools.imap for deferred callables using cooperative multitasking
    """
    results = []
    yield coop(asyncCallable, results.append, *iterables)
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
def asyncStarPmap(asyncCallable, iterable, workers=0):
    """itertools.starmap for deferred callables using parallel cooperative
    multitasking
    """
    results = []
    yield asyncStarParallel(asyncCallable, results.append, iterable, workers=workers)
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


def def2unicode(entitydef):
    """Convert an HTML entity reference into unicode.
    """
    def2name = {v: k for k, v in entitydefs.items()}
    name = def2name[entitydef]
    cp = name2codepoint[name]
    return unichr(cp)


def elementToDict(element, tag='content'):
    """Convert a microdom element into a dict imitating how Yahoo Pipes does it.

    TODO: checkout twisted.words.xish
    """
    try:
        i = dict(element.attributes)
    except AttributeError:
        i = {}

    value = element.nodeValue if hasattr(element, 'nodeValue') else None

    if isinstance(element, EntityReference):
        value = def2unicode(value)

    i.update(_make_content(i, value, tag))

    if element.hasChildNodes():
        for child in element.childNodes:
            try:
                tag = child.tagName
            except AttributeError:
                tag = 'content'

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
