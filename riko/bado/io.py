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

from io import TextIOWrapper
from os import remove
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING, Union, override

import pygogo as gogo

from riko import ENCODING, get_abspath

try:
    from twisted.internet import testing
except ImportError:
    testing = None
    failure = None
    reactor = None
    FileSender = None
    treq = None
else:
    import treq
    from twisted.internet import reactor
    from twisted.protocols.basic import FileSender
    from twisted.python import failure

if TYPE_CHECKING:
    from twisted.internet.defer import Deferred
    from twisted.internet.interfaces import IConsumer
    from twisted.internet.testing import StringTransport
    from twisted.python.failure import Failure


logger = gogo.Gogo(__name__, monolog=True).logger
CHUNK_SIZE = 8


# http://stackoverflow.com/q/26314586/408556
# http://stackoverflow.com/q/8157197/408556
# http://stackoverflow.com/a/33708936/408556
class FileReader(testing.AccumulatingProtocol):
    transport: "StringTransport"  # type: ignore[reportIncompatibleVariableOverride]
    consumer: "IConsumer"  # set by registerProducer
    lastSent: bytes  # noqa: N815 set by FileSender.resumeProducing
    deferred: Union["Deferred", None]

    def __init__(
        self,
        filename: str,
        transform=None,
        delay: float = 0,
        chunk_size: int = CHUNK_SIZE,
        verbose: bool = False,
    ):
        self.chunk_size = chunk_size
        self.f = open(filename, "rb")  # noqa: SIM115
        self.transform = transform
        self.delay = delay
        self.producer = FileSender()
        self.logger = gogo.Gogo(__name__, verbose=verbose).logger

    def cleanup(self, *_):
        self.f.close()
        self.producer.stopProducing()

    @override
    def resumeProducing(self):
        chunk = self.f.read(self.chunk_size) if self.f else b""

        if not chunk:
            self.f = None
            self.consumer.unregisterProducer()

            if self.deferred and self.delay:
                # IDelayedCall stub missing delay param
                args = (self.delay, self.deferred.callback, self.lastSent)
                reactor.callLater(*args)  # type: ignore[arg-type]
            elif self.deferred:
                self.deferred.callback(self.lastSent)

            self.deferred = None
            return

    @override
    def connectionLost(self, reason: Union["Failure", None] = None):
        reason = reason or failure.Failure(Exception("unknown"))
        self.logger.debug(f"connectionLost: {reason}")
        self.cleanup()

    @override
    def connectionMade(self):
        self.logger.debug(f"Connection made from {self.transport.getPeer()}")
        args = (self.f, self.transport, self.transform)
        self.d = self.closedDeferred = self.producer.beginFileTransfer(*args)

        while not self.d.called:
            self.producer.resumeProducing()

        self.d.addErrback(self.logger.error)
        self.d.addBoth(self.cleanup)


async def async_read_file(
    filename: str, transport, protocol=FileReader, encoding=ENCODING, **kwargs
) -> str:
    proto = protocol(filename.replace("file://", ""), **kwargs)
    proto.makeConnection(transport)
    await proto.d
    value = proto.transport.value()
    return value.decode(encoding)


class NamedTextIOWrapper(TextIOWrapper):
    _name: str = ""

    @property
    def name(self) -> str:  # type: ignore[override]
        return self._name

    @name.setter
    def name(self, value: str) -> None:
        self._name = value


async def async_get_file(
    filename: str,
    transport: "StringTransport",
    protocol=FileReader,
    encoding=ENCODING,
    **kwargs,
) -> NamedTextIOWrapper:
    """
    Raises:
        proto.transport.io.seek
            UnsupportedOperation — if io isn't seekable

    """
    proto = protocol(filename.replace("file://", ""), **kwargs)
    proto.makeConnection(transport)
    await proto.d
    proto.transport.io.seek(0)
    f = proto.transport.io
    return NamedTextIOWrapper(f, encoding=encoding)


async def async_url_open(url: str, timeout=0, **kwargs) -> NamedTextIOWrapper:
    """
    Raises:
        NamedTemporaryFile
            OSError / PermissionError — no write permission in the temp directory
            FileNotFoundError — temp dir doesn't exist (rare but possible in containers)

        await treq.get
            twisted.internet.error.ConnectionRefusedError — server actively refused
            twisted.internet.error.DNSLookupError — hostname doesn't resolve
            twisted.internet.error.TimeoutError — connection timed out
            twisted.internet.error.ConnectionLost / ConnectionDone — dropped mid-request
            twisted.web.error.SchemeNotSupported — non-http/https scheme slips through
                if the url.startswith("http") check passes but treq can't handle it

        await response.text
            UnicodeDecodeError — if the response body can't be decoded with the default
                encoding

        page.write
            OSError — disk full, or temp file was externally deleted between creation
                and write

    """
    if url.startswith("http"):
        page = NamedTemporaryFile(delete=False, mode="w")  # noqa: SIM115
        new_url = page.name
        response = await treq.get(url, timeout=timeout)
        content = await response.text()
        page.write(content)
        page.flush()
        file_name = url.split("://")[1] if url.startswith("file") else None
    else:
        page, new_url, file_name = None, url, None

    f = await async_get_file(new_url, testing.StringTransport(), **kwargs)

    if not hasattr(f, "name") and file_name:
        f.name = file_name

    if page:
        page.close()
        remove(page.name)

    return f


async def async_url_read(url: str, timeout=0, **kwargs) -> str:
    url = get_abspath(url, offline=True)

    if url.startswith("http"):
        response = await treq.get(url, timeout=timeout)
        content = await response.text()
    else:
        content = await async_read_file(url, testing.StringTransport(), **kwargs)

    return content
