# vim: sw=4:ts=4:expandtab
"""
Reusable loopback HTTP server for exercising riko's fetch path offline.

A real socket server on ``127.0.0.1`` so tests drive the actual HTTP stack
(``requests``, streaming vs. buffered reads, gzip, response close) without
touching the internet. Prefer this over monkeypatching the client whenever a
test cares about transport; reach for a mock only when the point is pure logic
that does not depend on how the bytes arrive.

Basic usage::

    from tests._loopback import loopback_url

    with loopback_url("<rss>...</rss>", content_type="application/xml") as url:
        pipeline = Pipeline.from_module("fetch", conf={"url": url})

Tests that use this should carry ``@pytest.mark.simulated_network``.
``ForwardOnly`` stands in for a fetched response body (``r.raw``) when a test needs a
binary stream that cannot seek, without a server.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager, suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO, RawIOBase
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Generator

    from riko.types._scalars import AnyStr


CHUNK = 8192


class ForwardOnly(RawIOBase):
    """A binary stream that reads ``data`` once and cannot seek."""

    def __init__(self, data: bytes) -> None:
        super().__init__()
        self.inner = BytesIO(data)

    def readable(self) -> bool:
        return True

    def readinto(self, b) -> int:
        return self.inner.readinto(b)


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request: object, client_address: object) -> None:
        pass


def _make_handler(
    body: bytes,
    content_type: str,
    status: int,
    echo: str | None,
    seen: list[str] | None,
) -> type[BaseHTTPRequestHandler]:
    class _Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            if seen is not None:
                seen.append(self.headers.get("User-Agent", ""))

            payload = body if echo is None else self.headers.get(echo, "").encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()

            with suppress(BrokenPipeError, ConnectionResetError):
                for index in range(0, len(payload), CHUNK):
                    self.wfile.write(payload[index : index + CHUNK])

        def log_message(self, format: str, *args: object) -> None:
            pass

    return _Handler


@contextmanager
def loopback_url(
    body: AnyStr = "",
    *,
    content_type: str = "text/plain; charset=utf-8",
    status: int = 200,
    path: str = "feed.txt",
    echo: str | None = None,
    seen: list[str] | None = None,
) -> Generator[str]:
    """
    Serve *body* from an ephemeral loopback server and yield its URL.

    The server binds an OS-assigned port on ``127.0.0.1``, runs on a daemon
    thread, and is shut down on exit. *body* is served for any GET path, or,
    when *echo* names a request header, that header's value is served instead.
    Each request's ``User-Agent`` header is appended to *seen* when given.
    """
    payload = body.encode() if isinstance(body, str) else body
    server = _Server(
        ("127.0.0.1", 0), _make_handler(payload, content_type, status, echo, seen)
    )
    # A short poll interval keeps shutdown from waiting out the 0.5 s default.
    thread = threading.Thread(target=server.serve_forever, args=(0.01,), daemon=True)
    thread.start()

    try:
        yield f"http://127.0.0.1:{server.server_port}/{path}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)
