# vim: sw=4:ts=4:expandtab
"""
Tests riko.io._sync's HTTP openers against a real local server.

The streamed and memoized branches only diverge once bytes actually cross a
socket, so a fixture file cannot exercise them: the streamed text branch reads
``r.raw``, which is empty unless the request was made with ``stream=True``.
"""

from io import BytesIO
from os import linesep
from unittest.mock import Mock, patch
from urllib.response import addinfourl

import pytest
from requests import Response

from riko.base._paths import get_path
from riko.coercion._configs import CsvObjconf
from riko.io._async import async_url_open
from riko.io._reencode import Reencoder, reencode
from riko.io._sync import Fetch
from riko.modules import csv
from tests import async_test
from tests._loopback import loopback_url


def test_csv_headerless_closes_original_source(monkeypatch):
    """
    Ensure ``auto_close`` closes the original fetch after header buffering.

    With ``has_header=False``, ``seekable`` uses a spooled copy while leaving the
    original fetch open.
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


@pytest.mark.simulated_network
@pytest.mark.xfail(
    strict=True, reason="async_url_open ignores the Content-Type and decodes as utf-8"
)
@async_test
async def test_async_url_open_honors_content_type_charset():
    """
    Decode async responses using their declared charset.

    This matches the existing sync ``Fetch`` behavior.
    """
    body = "café ünïcode".encode("iso-8859-1")

    with loopback_url(
        body, content_type="text/plain; charset=iso-8859-1", path="p.txt"
    ) as url:
        async with async_url_open(url) as f:
            result = f.read()
            assert result
            assert "é" in result


@pytest.mark.simulated_network
@pytest.mark.xfail(
    strict=True,
    reason="owned by the pending encoding-precedence work: sync decoding keeps "
    "carriage returns that async decoding converts to newlines",
)
@async_test
async def test_sync_and_async_decode_line_endings_alike():
    """Decode carriage returns the same way in sync and async reads."""
    body = b"abc\rdef\n"
    sync_result = reencode(BytesIO(body), decode=True).read()

    with loopback_url(body, content_type="text/plain", path="p.txt") as url:
        async with async_url_open(url) as f:
            assert sync_result == f.read()


class TestReencode:
    @pytest.mark.parametrize("method", ["read", "chunks", "readlines"])
    def test_line_without_trailing_newline_round_trips(self, method):
        """A single unterminated line decodes to the same text however it is read."""
        text = "<r><t>café</t></r>"
        reader = reencode(BytesIO(text.encode()), decode=True)

        if method == "read":
            result = reader.read()
        elif method == "chunks":
            result = "".join(iter(lambda: reader.read(4), ""))
        else:
            result = "".join(iter(reader.readline, ""))

        assert result == text

    @pytest.mark.parametrize("size", [1, 3, 5])
    def test_foreign_newlines_read_in_chunks_match_full_read(self, size):
        """Sized reads of carriage-return lines keep every separator within ``n``."""
        data = b"abc\rdef\rghi"
        full = reencode(BytesIO(data), decode=True).read()
        reader = reencode(BytesIO(data), decode=True)
        chunks = list(iter(lambda: reader.read(size), ""))

        assert full == linesep.join(["abc", "def", "ghi"])
        assert all(len(chunk) <= size for chunk in chunks)
        assert "".join(chunks) == full

    def test_foreign_newlines_readline_keeps_ends(self):
        """Carriage-return lines come back with a line ending unless asked not to."""
        data = b"abc\rdef\rghi"
        reader = reencode(BytesIO(data), decode=True)
        bare = reencode(BytesIO(data), decode=True).readlines(keepends=False)

        assert reader.readlines() == [f"abc{linesep}", f"def{linesep}", "ghi"]
        assert bare == ["abc", "def", "ghi"]

    @pytest.mark.parametrize(
        ("data", "expected"),
        [
            (b"abc\r\rdef", ["abc", "", "def"]),
            (b"\rabc", ["", "abc"]),
            (b"abc\rdef\r", ["abc", "def", ""]),
        ],
    )
    def test_foreign_newlines_keep_blank_lines(self, data, expected):
        """Each carriage return ends exactly one line, so blank lines survive."""
        full = reencode(BytesIO(data), decode=True).read()
        lines = reencode(BytesIO(data), decode=True).readlines()

        assert full == linesep.join(expected)
        assert "".join(lines) == full
        assert list(reencode(BytesIO(data), decode=True)) == lines

    @pytest.mark.parametrize("encoding", ["utf-16", "utf-16-le"])
    def test_wide_encoding_keeps_every_line(self, encoding):
        """A source whose newline spans several bytes decodes in full, line by line."""
        data = "a\nb\r\nc\n".encode(encoding)
        assert reencode(BytesIO(data), encoding, decode=True).read() == "a\nb\nc\n"
        reader = reencode(BytesIO(data), encoding, decode=True)
        assert list(iter(reader.readline, "")) == ["a\n", "b\n", "c\n"]

    def test_wide_encoding_reencodes_in_full(self):
        """Re-encoding a multi-line wide-encoded source keeps every byte."""
        data = "a\nb\nc\n".encode("utf-16")
        assert reencode(BytesIO(data), "utf-16").read() == b"a\nb\nc\n"

    @pytest.mark.parametrize(
        ("data", "kwargs", "expected"),
        [
            (b"", {"decode": True}, ""),
            (b"", {}, b""),
            (b"\xff\xfe", {"fromenc": "utf-16", "decode": True}, ""),
        ],
    )
    def test_empty_source_reads_empty(self, data, kwargs, expected):
        """A source with no content reads as empty instead of raising."""
        reader = reencode(BytesIO(data), **kwargs)
        assert reader.read() == expected
        assert reader.readline() == expected

    def test_empty_file_fetches_as_empty_text(self, tmp_path):
        """Fetching an empty text file reads nothing instead of raising."""
        path = tmp_path / "empty.txt"
        path.write_bytes(b"")

        with Fetch(path.as_uri()) as f:
            assert f.read() == ""

    def test_failed_open_closes_the_source(self):
        """A source that fails while the reader is being opened is closed."""

        class BrokenSource(BytesIO):
            def __next__(self):
                raise OSError("unreadable")

        source = BrokenSource(b"<r/>")

        with pytest.raises(OSError, match="unreadable"):
            reencode(source, decode=True)

        assert source.closed

    def test_failed_decode_closes_the_fetched_file(self, tmp_path):
        """A fetched file that fails to decode is closed rather than leaked."""
        path = tmp_path / "latin1.txt"
        path.write_bytes("<r>café</r>".encode("latin-1"))
        fetched = Fetch(path.as_uri())
        assert isinstance(fetched.file, Reencoder)
        handle = fetched.file._f
        assert isinstance(handle, addinfourl)

        with pytest.raises(UnicodeDecodeError), fetched:
            fetched.read()

        assert handle.closed

    @pytest.mark.parametrize(
        ("kwargs", "expected"),
        [
            ({"decode": True}, "\ufeff<r/>\n"),
            ({"decode": True, "remove_BOM": True}, "<r/>\n"),
            ({"remove_BOM": True}, b"<r/>\n"),
        ],
    )
    def test_remove_bom_strips_the_byte_order_mark(self, kwargs, expected):
        """``remove_BOM`` drops a leading byte order mark; it is kept by default."""
        data = b"\xef\xbb\xbf<r/>\n"
        assert reencode(BytesIO(data), **kwargs).read() == expected

    @pytest.mark.parametrize("method", ["read", "readline"])
    def test_char_count_preserves_remainder(self, method):
        """A one-character read consumes only that character."""
        data = b"line one\nline two\nline three\n"
        full = reencode(BytesIO(data), decode=True).read()
        reader = reencode(BytesIO(data), decode=True)
        head = getattr(reader, method)(1)
        rest = reader.read()

        assert head == "l"
        assert rest == "ine one\nline two\nline three\n"
        assert head + rest == full

    @pytest.mark.parametrize("method", ["read", "readline"])
    def test_zero_size_reads_nothing(self, method):
        """A zero-size read returns empty and leaves the whole stream unread."""
        data = b"line one\nline two\n"
        reader = reencode(BytesIO(data), decode=True)

        assert getattr(reader, method)(0) == ""
        assert reader.read() == data.decode()

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
        """Route parameterless HTTP URLs through the requests backend."""
        response = Mock()
        response.headers = {"Content-Type": "application/rss+xml"}
        target = "http://example.com/feed.xml"

        with (
            patch("riko.io._sync.requests.get", return_value=response) as mock_requests,
            patch("riko.io._sync.urlopen") as mock_urlopen,
        ):
            Fetch(target, binary=True)

        mock_requests.assert_called_once()
        mock_urlopen.assert_not_called()
        assert mock_requests.call_args.args[0] == target
