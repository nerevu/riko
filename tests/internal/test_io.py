# vim: sw=4:ts=4:expandtab
"""
Tests riko._io's HTTP openers against a real local server.

The streamed and memoized branches only diverge once bytes actually cross a
socket, so a fixture file cannot exercise them: the streamed text branch reads
``r.raw``, which is empty unless the request was made with ``stream=True``.
"""

from typing import Any, cast
from unittest.mock import Mock, patch

import pytest
from requests import Response

from riko._io import Fetch
from tests._loopback import loopback_url

BODY = "".join(f"line {index} ünïcode\n" for index in range(2000))
PAYLOAD = BODY.encode()


@pytest.fixture(scope="module")
def url():
    with loopback_url(BODY) as served:
        yield served


def test_unified_http_backend():
    """
    A params-less http URL routes through the requests backend rather than the
    urllib opener.
    """
    response = Mock()
    response.headers = {"Content-Type": "application/rss+xml"}
    target = "http://example.com/feed.xml"

    with (
        patch("riko._io.requests.get", return_value=response) as mock_requests,
        patch("riko._io.urlopen") as mock_urlopen,
    ):
        Fetch(target, binary=True)

    mock_requests.assert_called_once()
    mock_urlopen.assert_not_called()
    assert mock_requests.call_args.args[0] == target


@pytest.mark.simulated_network
class TestLoopbackServer:
    """The streamed/memoized branches exercised against a real loopback server."""

    def test_streamed_text_read_returns_full_body(self, url):
        with Fetch(url) as f:
            assert f.read() == BODY

    def test_streamed_text_iterates_every_line(self, url):
        with Fetch(url) as f:
            lines = list(f)

        assert len(lines) == 2000
        assert lines[-1] == "line 1999 ünïcode\n"

    def test_streamed_text_closes_its_response(self, url):
        f = Fetch(url)
        response = cast(Response, cast(Any, f.file)._f)
        f.close()

        assert response.raw.closed

    def test_memoized_text_matches_streamed(self, url):
        with Fetch(url, memoize=True) as f:
            assert f.read() == BODY

    def test_streamed_binary_read_returns_payload(self, url):
        with Fetch(url, binary=True) as f:
            assert f.read() == PAYLOAD
