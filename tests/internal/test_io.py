# vim: sw=4:ts=4:expandtab
"""
Tests riko._io's HTTP openers against a real local server.

The streamed and memoized branches only diverge once bytes actually cross a
socket, so a fixture file cannot exercise them: the streamed text branch reads
``r.raw``, which is empty unless the request was made with ``stream=True``.
"""

import threading
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, cast

import pytest
from requests import Response

from riko._io import Fetch

BODY = "".join(f"line {index} ünïcode\n" for index in range(2000))
PAYLOAD = BODY.encode()
CHUNK = 8192


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(PAYLOAD)))
        self.end_headers()

        with suppress(BrokenPipeError, ConnectionResetError):
            for index in range(0, len(PAYLOAD), CHUNK):
                self.wfile.write(PAYLOAD[index : index + CHUNK])

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request: object, client_address: object) -> None:
        pass


@pytest.fixture(scope="module")
def url():
    server = _Server(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    yield f"http://127.0.0.1:{server.server_port}/feed.txt"

    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def test_streamed_text_read_returns_full_body(url):
    with Fetch(url) as f:
        assert f.read() == BODY


def test_streamed_text_iterates_every_line(url):
    with Fetch(url) as f:
        lines = list(f)

    assert len(lines) == 2000
    assert lines[-1] == "line 1999 ünïcode\n"


def test_streamed_text_closes_its_response(url):
    f = Fetch(url)
    response = cast(Response, cast(Any, f.file)._f)
    f.close()

    assert response.raw.closed


def test_memoized_text_matches_streamed(url):
    with Fetch(url, memoize=True) as f:
        assert f.read() == BODY


def test_streamed_binary_read_returns_payload(url):
    with Fetch(url, binary=True) as f:
        assert f.read() == PAYLOAD
