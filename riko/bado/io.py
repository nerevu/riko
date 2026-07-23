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

from io import BytesIO, TextIOWrapper
from os import remove
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING, Literal, Union, overload, override

import pygogo as gogo

from riko import ENCODING, bado, get_abspath
from riko.bado import FileSender, async_get, failure, testing

if TYPE_CHECKING:
    from twisted.internet.defer import Deferred
    from twisted.internet.interfaces import IConsumer
    from twisted.internet.testing import StringTransport
    from twisted.python.failure import Failure


logger = gogo.Gogo(__name__, monolog=True).logger
CHUNK_SIZE = 32 * 1024  # 32KB


# http://stackoverflow.com/q/26314586/408556
# http://stackoverflow.com/q/8157197/408556
# http://stackoverflow.com/a/33708936/408556
_AccumulatingProtocol = testing.AccumulatingProtocol if testing is not None else object


class FileReader(_AccumulatingProtocol):  # type: ignore[misc]
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
                bado.reactor.callLater(*args)  # type: ignore[arg-type]
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


@overload
async def async_get_file(  # noqa: E704
    filename: str,
    transport: "StringTransport",
    protocol=...,
    encoding: str = ...,
    *,
    binary: Literal[True],
    **kwargs,
) -> BytesIO: ...
@overload  # noqa: E302
async def async_get_file(  # noqa: E704
    filename: str,
    transport: "StringTransport",
    protocol=...,
    encoding: str = ...,
    binary: Literal[False] = ...,
    **kwargs,
) -> NamedTextIOWrapper: ...
async def async_get_file(  # noqa: E302
    filename: str,
    transport: "StringTransport",
    protocol=FileReader,
    encoding=ENCODING,
    binary: bool = False,
    **kwargs,
) -> BytesIO | NamedTextIOWrapper:
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
    return f if binary else NamedTextIOWrapper(f, encoding=encoding)


@overload
async def async_url_open(  # noqa: E704
    url: str, timeout: float = ..., *, binary: Literal[True], **kwargs
) -> BytesIO: ...
@overload  # noqa: E302
async def async_url_open(  # noqa: E704
    url: str, timeout: float = ..., binary: Literal[False] = ..., **kwargs
) -> NamedTextIOWrapper: ...
async def async_url_open(  # noqa: E302
    url: str, timeout: float = 0, binary: bool = False, **kwargs
) -> BytesIO | NamedTextIOWrapper:
    """
    Raises:
        NamedTemporaryFile
            OSError / PermissionError — no write permission in the temp directory
            FileNotFoundError — temp dir doesn't exist (rare but possible in containers)

        await async_get
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
    page = None

    try:
        if url.startswith("http"):
            mode = "wb" if binary else "w"
            page = NamedTemporaryFile(delete=False, mode=mode)  # noqa: SIM115
            new_url = page.name
            response = await async_get(url, timeout=timeout)
            content = await (response.content() if binary else response.text())
            page.write(content)
            page.flush()
        else:
            new_url = url

        f = await async_get_file(
            new_url, testing.StringTransport(), binary=binary, **kwargs
        )
    finally:
        if page:
            page.close()

            try:
                remove(page.name)
            except OSError:
                logger.debug(f"Could not remove temp file {page.name}")

    return f


async def async_url_read(url: str, timeout=0, **kwargs) -> str:
    url = get_abspath(url, offline=True)

    if url.startswith("http"):
        response = await async_get(url, timeout=timeout)
        content = await response.text()
    else:
        content = await async_read_file(url, testing.StringTransport(), **kwargs)

    return content
