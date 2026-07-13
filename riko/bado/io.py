# vim: sw=4:ts=4:expandtab
"""
riko.bado.io
~~~~~~~~~~~~
Provides functions for asynchronously reading files and urls

Examples:
    basic usage::

        >>> from riko import get_path
        >>> from riko.bado.io import async_url_open

"""

import builtins
from collections.abc import Generator
from io import StringIO
from os import remove
from tempfile import NamedTemporaryFile
from typing import cast

import pygogo as gogo

from riko import ENCODING, get_abspath

from . import coroutine, return_value

try:
    from twisted.internet.testing import AccumulatingProtocol
except ImportError:
    AccumulatingProtocol = callLater = StringTransport = FileSender = treq = object
else:
    import treq
    from twisted.internet.defer import Deferred
    from twisted.internet.reactor import callLater
    from twisted.internet.testing import StringTransport
    from twisted.protocols.basic import FileSender

logger = gogo.Gogo(__name__, monolog=True).logger


# http://stackoverflow.com/q/26314586/408556
# http://stackoverflow.com/q/8157197/408556
# http://stackoverflow.com/a/33708936/408556
class FileReader(AccumulatingProtocol):
    def __init__(self, filename, transform=None, delay=0, verbose=False):
        self.f = builtins.open(filename, "rb")
        self.transform = transform
        self.delay = delay
        self.producer = FileSender()
        self.logger = gogo.Gogo(__name__, verbose=verbose).logger

    def cleanup(self, *args):
        self.f.close()
        self.producer.stopProducing()

    def resumeProducing(self):
        chunk = self.file.read(self.CHUNK_SIZE) if self.file else ""

        if not chunk:
            self.file = None
            self.consumer.unregisterProducer()

            if self.deferred and self.delay:
                callLater(self.delay, self.deferred.callback, self.lastSent)  # pyright: ignore[reportCallIssue]
            elif self.deferred:
                self.deferred.callback(self.lastSent)

            self.deferred = None
            return

    def connectionLost(self, reason):
        self.logger.debug("connectionLost: %s", reason)
        self.cleanup()

    def connectionMade(self):
        self.logger.debug("Connection made from %s", self.transport.getPeer())
        args = (self.f, self.transport, self.transform)
        self.d = self.closedDeferred = self.producer.beginFileTransfer(*args)

        while not self.d.called:
            self.producer.resumeProducing()

        self.d.addErrback(self.logger.error)
        self.d.addBoth(self.cleanup)


@coroutine  # pyright: ignore[reportArgumentType]
def async_read_file(
    filename: str, transport, protocol=FileReader, encoding=ENCODING, **kwargs
) -> Generator[Deferred[str], str, None]:
    proto = protocol(filename.replace("file://", ""), **kwargs)
    proto.makeConnection(transport)
    yield proto.d
    value: bytes = proto.transport.value()
    return_value(value.decode(encoding))


@coroutine  # pyright: ignore[reportArgumentType]
def async_get_file(
    filename: str, transport, protocol=FileReader, **kwargs
) -> Generator[Deferred[StringIO], StringIO, None]:
    proto = protocol(filename.replace("file://", ""), **kwargs)
    proto.makeConnection(transport)
    yield proto.d
    proto.transport.io.seek(0)
    f = cast(StringIO, proto.transport.io)
    return_value(f)


@coroutine  # pyright: ignore[reportArgumentType]
def async_url_open(
    url: str, timeout=0, encoding=ENCODING, **kwargs
) -> Generator[Deferred[StringIO], StringIO, None]:
    if url.startswith("http"):
        page = NamedTemporaryFile(delete=False, mode="w")
        new_url = page.name
        response = yield treq.get(url)  # pyright: ignore[reportAttributeAccessIssue]
        content = yield response.text()  # pyright: ignore[reportAttributeAccessIssue]
        page.write(cast(str, content))
        page.flush()
        file_name = url.split("://")[1] if url.startswith("file") else None
    else:
        page, new_url, file_name = None, url, None

    f = yield async_get_file(new_url, StringTransport(), **kwargs)  # pyright: ignore[reportCallIssue]

    if not hasattr(f, "name") and file_name:
        f.name = file_name

    if page:
        page.close()
        remove(page.name)

    return_value(f)


@coroutine  # pyright: ignore[reportArgumentType]
def async_url_read(
    url: str, timeout=0, **kwargs
) -> Generator[Deferred[str], str, None]:
    url = get_abspath(url, offline=True)

    if url.startswith("http"):
        response = yield treq.get(url)  # pyright: ignore[reportAttributeAccessIssue]
        content = yield response.text()  # pyright: ignore[reportAttributeAccessIssue]
    else:
        content = yield async_read_file(url, StringTransport(), **kwargs)  # pyright: ignore[reportReturnType, reportCallIssue]

    return_value(content)
