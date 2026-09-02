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
        stream = SyncPipe("fetch", conf={"url": url})

Tests that use this should carry ``@pytest.mark.simulated_network``.
"""

import threading
from collections.abc import Generator
from contextlib import contextmanager, suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from riko.types._scalars import AnyStr

CHUNK = 8192


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request: object, client_address: object) -> None:
        pass


def _make_handler(
    payload: bytes, content_type: str, status: int
) -> type[BaseHTTPRequestHandler]:
    class _Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:  # noqa: N802
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()

            with suppress(BrokenPipeError, ConnectionResetError):
                for index in range(0, len(payload), CHUNK):
                    self.wfile.write(payload[index : index + CHUNK])

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            pass

    return _Handler


@contextmanager
def loopback_url(
    body: AnyStr = "",
    *,
    content_type: str = "text/plain; charset=utf-8",
    status: int = 200,
    path: str = "feed.txt",
) -> Generator[str]:
    """
    Serve *body* from an ephemeral loopback server and yield its URL.

    The server binds an OS-assigned port on ``127.0.0.1``, runs on a daemon
    thread, and is torn down on exit. *body* is served for any GET path.
    """
    payload = body.encode() if isinstance(body, str) else body
    server = _Server(("127.0.0.1", 0), _make_handler(payload, content_type, status))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        yield f"http://127.0.0.1:{server.server_port}/{path}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
