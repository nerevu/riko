# vim: sw=4:ts=4:expandtab
"""
Tests riko._io's HTTP openers against a real local server.

The streamed and memoized branches only diverge once bytes actually cross a
socket, so a fixture file cannot exercise them: the streamed text branch reads
``r.raw``, which is empty unless the request was made with ``stream=True``.
"""

from io import BytesIO
from unittest.mock import Mock, patch

import pytest
from requests import Response

from riko._io import Fetch
from riko._reencode import Reencoder, reencode
from riko.modules import csv
from riko.paths import get_path
from riko.types._configs import CsvObjconf
from tests._loopback import loopback_url


def test_csv_headerless_closes_original_source(monkeypatch):
    """
    ``has_header=False`` buffers through ``seekable`` (a spooled copy) and leaves the
    original fetch open. ``auto_close`` must still close it, not just the spool.
    """
    closed: list[bool] = []
    real_fetch = csv.Fetch

    class _SpyFetch(real_fetch):
        def close(self) -> None:
            closed.append(True)
            super().close()

    monkeypatch.setattr(csv, "Fetch", _SpyFetch)
    conf = CsvObjconf(
        {
            "url": get_path("countries.csv"),
            "has_header": False,
            "skip_rows": 0,
            "col_names": None,
            "encoding": "utf-8",
            "sanitize": False,
            "dedupe": True,
        }
    )

    list(csv.parser({}, None, conf))
    assert closed


class TestReencode:
    def test_reencode_read_honors_char_count(self):
        """``read(1)`` yields a single character and the remainder survives."""
        data = b"line one\nline two\nline three\n"
        full = reencode(BytesIO(data), decode=True).read()
        reader = reencode(BytesIO(data), decode=True)
        head, rest = reader.read(1), reader.read()

        assert head == "l"
        assert rest == "ine one\nline two\nline three\n"
        assert head + rest == full

    def test_reencode_readline_honors_char_count(self):
        """``readline(1)`` yields a single character and the remainder survives."""
        data = b"line one\nline two\nline three\n"
        full = reencode(BytesIO(data), decode=True).read()
        reader = reencode(BytesIO(data), decode=True)
        head, rest = reader.readline(1), reader.read()

        assert head == "l"
        assert rest == "ine one\nline two\nline three\n"
        assert head + rest == full

    def test_reencode_readline(self):
        data = b"line one\nline two\nline three\n"
        full = reencode(BytesIO(data), decode=True).readlines(keepends=False)
        reader = reencode(BytesIO(data), decode=True)
        head, rest = reader.readline(keepends=False), reader.readlines(keepends=False)

        assert head == "line one"
        assert rest == ["line two", "line three"]
        assert [head] + rest == full

    def test_reencode_read_and_readline(self):
        data = b"line one\nline two\nline three\n"
        full = reencode(BytesIO(data), decode=True).read()
        reader = reencode(BytesIO(data), decode=True)
        head, mid, rest = reader.read(1), reader.readline(), reader.readlines()

        assert head == "l"
        assert mid == "ine one\n"
        assert rest == ["line two\n", "line three\n"]
        assert head + mid + "".join(rest) == full


@pytest.mark.simulated_network
class TestLoopbackServer:
    """The streamed/memoized branches exercised against a real loopback server."""

    BODY = "".join(f"line {index} ünïcode\n" for index in range(2000))
    PAYLOAD = BODY.encode()

    @pytest.fixture(scope="class")
    def url(self):
        with loopback_url(self.BODY) as served:
            yield served

    def test_streamed_text_read_returns_full_body(self, url):
        with Fetch(url) as f:
            assert f.read() == self.BODY

    def test_streamed_text_iterates_every_line(self, url):
        with Fetch(url) as f:
            lines = list(f)

        assert len(lines) == 2000
        assert lines[-1] == "line 1999 ünïcode\n"

    def test_streamed_text_closes_its_response(self, url):
        f = Fetch(url)
        assert isinstance(f.file, Reencoder)
        response = f.file._f
        assert isinstance(response, Response)
        f.close()

        assert response.raw.closed

    def test_memoized_text_matches_streamed(self, url):
        with Fetch(url, memoize=True) as f:
            assert f.read() == self.BODY

    def test_streamed_binary_read_returns_payload(self, url):
        with Fetch(url, binary=True) as f:
            assert f.read() == self.PAYLOAD

    def test_unified_http_backend(self):
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
