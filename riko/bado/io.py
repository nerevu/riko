# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.bado.io
~~~~~~~~~~~~
Provides functions for asynchronously reading files and urls

Examples:
    basic usage::

        >>> from riko import get_path
        >>> from riko.bado.io import urlOpen
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

import pygogo as gogo

from io import StringIO, open

from builtins import *
from meza._compat import encode

from . import coroutine, return_value

try:
    from twisted.test.proto_helpers import AccumulatingProtocol
except ImportError:
    AccumulatingProtocol = object
else:
    from twisted.internet.reactor import callLater
    from twisted.protocols.basic import FileSender
    from twisted.web.client import getPage, downloadPage
    from twisted.test.proto_helpers import StringTransport

logger = gogo.Gogo(__name__, monolog=True).logger


# http://stackoverflow.com/q/26314586/408556
# http://stackoverflow.com/q/8157197/408556
# http://stackoverflow.com/a/33708936/408556
class FileReader(AccumulatingProtocol):
    def __init__(self, filename, transform=None, delay=0, verbose=False):
        self.f = open(filename, 'rb')
        self.transform = transform
        self.delay = delay
        self.producer = FileSender()
        self.logger = gogo.Gogo(__name__, verbose=verbose).logger

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
                callLater(self.delay, self.deferred.callback, self.lastSent)
            elif self.deferred:
                self.deferred.callback(self.lastSent)

            self.deferred = None
            return

    def connectionLost(self, reason):
        self.logger.debug('connectionLost: %s', reason)
        self.cleanup()

    def connectionMade(self):
        self.logger.debug('Connection made from %s', self.transport.getPeer())
        args = (self.f, self.transport, self.transform)
        self.d = self.closedDeferred = self.producer.beginFileTransfer(*args)

        while not self.d.called:
            self.producer.resumeProducing()

        self.d.addErrback(self.logger.error)
        self.d.addBoth(self.cleanup)


@coroutine
def readFile(filename, transport, protocol=FileReader, **kwargs):
    proto = protocol(filename.replace('file://', ''), **kwargs)
    proto.makeConnection(transport)
    yield proto.d
    # return_value(proto.data)
    return_value(proto.transport.value())


@coroutine
def getFile(filename, transport, protocol=FileReader, **kwargs):
    proto = protocol(filename.replace('file://', ''), **kwargs)
    proto.makeConnection(transport)
    yield proto.d
    proto.transport.io.seek(0)
    return_value(proto.transport.io)


@coroutine
def urlOpen(url, timeout=0, **kwargs):
    if url.startswith('http'):
        # returns unicode in py2 but bytes in py3
        f = StringIO()
        yield downloadPage(encode(url), f, timeout=timeout)
        f.seek(0)
    else:
        f = yield getFile(url, StringTransport(), **kwargs)

    return_value(f)


def urlRead(url, timeout=0, **kwargs):
    if url.startswith('http'):
        content = getPage(encode(url), timeout=timeout)
    else:
        content = readFile(url, StringTransport(), **kwargs)

    return content
