# vim: sw=4:ts=4:expandtab
"""Provides internal tests for URL/file I/O, re-encoding, and async stream helpers."""

from __future__ import annotations

from functools import partial
from importlib.metadata import EntryPoint
from io import BytesIO, StringIO
from os import linesep
from typing import TYPE_CHECKING
from unittest.mock import Mock, patch
from urllib.response import addinfourl

import pytest
from requests import Response
from requests.exceptions import Timeout

from riko.bado import as_async
from riko.bado._backend import Semaphore, TimeoutException, async_sleep, lowlevel
from riko.bado._util import async_return, gather_results
from riko.bado.itertools import async_map_ordered_stream, async_map_stream, async_merge
from riko.base._config import settings
from riko.base._exceptions import PipelineStateError, UnsupportedTargetError
from riko.definitions._targets import FileTarget, build_write
from riko.definitions._write import WriteResult
from riko.io._async import _chunk_content, async_url_open
from riko.io._reencode import Reencoder, reencode
from riko.io._serialization import CONVERSION_FUNCS
from riko.io._sync import Fetch
from riko.modules.tail import async_pipe as async_tail
from riko.modules.tail import pipe as tail
from riko.parsing.documents import IJSON_IS_NATIVE, IS_FASTFEEDPARSER, IS_LXML
from riko.runtime import _write_session
from riko.runtime._export import export
from riko.runtime._target_registry import TargetRegistry
from riko.runtime._write_session import (
    _SessionState,
    _SyncFileWriteSession,
    async_file_write_session,
    awrite_through,
    file_write_session,
    write_through,
)
from riko.types._enums import Formats
from tests import aresolve, async_test, is_installed, skipif_issync
from tests._lifecycle import ITEMS
from tests._loopback import URL, loopback_url, stalled_url, stub_async_get
from tests._targets import RecordStore

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterator

    from riko.types._io import PathLike
    from riko.types._streams import Feed, Items


async def _double(x: int) -> int:
    return x * 2


_LOOPBACK_BODY = "".join(f"line {index} ünïcode\n" for index in range(2000))
_MAP = partial(async_map_stream, _double, range(3))
_ORDERED = partial(async_map_ordered_stream, _double, range(3))
_MERGE = partial(async_merge, [])
_X0, _X1 = [{"x": 0}], [{"x": 1}]
_CSV0, _CSV012 = b"x\r\n0\r\n", b"x\r\n0\r\n1\r\n2\r\n"
_JSON0, _JSON01 = b'{"x": 0}\n', b'{"x": 0}\n{"x": 1}\n'

# A replace write leaves the old content until it publishes the new one whole.
ATOMIC_PUBLICATION_PENDING = pytest.mark.xfail(
    strict=True, reason="atomic replace-write publication is not yet implemented"
)


def _never() -> bool:
    """Reports a graceful close rather than a termination."""
    return False


def _always() -> bool:
    """Reports a termination rather than a graceful close."""
    return True


def _sink(items: Items, dest: PathLike, mode: str = "replace", **kwargs) -> WriteResult:
    """Delivers the whole stream to *dest* and commits it, as a terminal write does."""
    with file_write_session(build_write(dest, mode, **kwargs)) as session:
        session.write(items)
        result = session.finalize()

    return result


@pytest.fixture(scope="module")
def served_url():
    """Serves the loopback body over a real socket for the streamed branches."""
    with loopback_url(_LOOPBACK_BODY) as served:
        yield served


class TestFetch:
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

    def test_default_timeout_comes_from_settings(self):
        """A fetch without a timeout waits ``RIKO_FETCH_TIMEOUT`` seconds."""
        response = Mock()
        response.headers = {"Content-Type": "text/plain"}

        with patch("riko.io._sync.requests.get", return_value=response) as mock_get:
            Fetch("http://example.com/feed.txt", binary=True)

        assert mock_get.call_args.kwargs["timeout"] == settings.fetch_timeout

    @pytest.mark.simulated_network
    def test_timeout_stops_a_stalled_read(self):
        with stalled_url() as url, pytest.raises(Timeout):
            Fetch(url, timeout=0.2)

    @pytest.mark.simulated_network
    def test_streamed_text_read_returns_full_body(self, served_url):
        with Fetch(served_url) as f:
            assert f.read() == _LOOPBACK_BODY

    @pytest.mark.simulated_network
    def test_streamed_text_iterates_every_line(self, served_url):
        with Fetch(served_url) as f:
            lines = list(f)

        assert len(lines) == 2000
        assert lines[-1] == "line 1999 ünïcode\n"

    @pytest.mark.simulated_network
    def test_streamed_text_closes_its_response(self, served_url):
        f = Fetch(served_url)
        assert isinstance(f.file, Reencoder)
        response = f.file._f
        assert isinstance(response, Response)
        f.close()

        assert response.raw.closed

    @pytest.mark.simulated_network
    def test_memoized_text_matches_streamed(self, served_url):
        with Fetch(served_url, memoize=True) as f:
            assert f.read() == _LOOPBACK_BODY

    @pytest.mark.simulated_network
    def test_streamed_binary_read_returns_payload(self, served_url):
        with Fetch(served_url, binary=True) as f:
            assert f.read() == _LOOPBACK_BODY.encode()

    def test_empty_file_fetches_as_empty_text(self, tmp_path):
        """Fetching an empty text file reads nothing instead of raising."""
        path = tmp_path / "empty.txt"
        path.write_bytes(b"")

        with Fetch(path.as_uri()) as f:
            assert f.read() == ""

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


class TestAsyncUrlOpen:
    @async_test
    async def test_ext_from_content_type(self, monkeypatch):
        content_type = "application/rss+xml; charset=utf-8"
        monkeypatch.setattr(
            "riko.io._async.async_get", stub_async_get(b"{}", content_type)
        )
        f = await async_url_open(URL)
        assert f.ext == "xml"
        assert f.content_type == content_type

    @async_test
    async def test_default_timeout_comes_from_settings(self, monkeypatch):
        """A fetch without a timeout waits ``RIKO_FETCH_TIMEOUT`` seconds."""
        seen: dict[str, object] = {}
        stub = stub_async_get(b"{}", "application/json")

        async def async_get(url: str, **kwargs: object):
            seen.update(kwargs)
            return await stub(url, **kwargs)

        monkeypatch.setattr("riko.io._async.async_get", async_get)
        await async_url_open(URL)
        assert seen["timeout"] == settings.fetch_timeout

    @pytest.mark.simulated_network
    @async_test
    async def test_timeout_stops_a_stalled_read(self):
        with stalled_url() as url, pytest.raises(TimeoutException):
            await async_url_open(url, timeout=0.2)

    @pytest.mark.simulated_network
    @pytest.mark.xfail(
        strict=True,
        reason="streaming async URL reads are not yet implemented: async_url_open "
        "buffers the whole body before returning, so a stalled body times out "
        "before the lines already received can be read",
    )
    @async_test
    async def test_async_url_open_reads_received_lines_before_the_body_ends(self):
        """The first line of a stalled body is readable, as with sync ``Fetch``."""
        prefix = b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n\r\nfirst\n"

        with stalled_url(prefix) as url:
            async with async_url_open(url, timeout=0.5) as f:
                assert f.readline() == "first\n"

    @async_test
    async def test_handle_is_reusable_but_not_reentrant(self, tmp_path):
        path = tmp_path / "data.txt"
        path.write_text("data")
        handle = async_url_open(str(path))

        async with handle as first:
            assert first.read() == "data"

            with pytest.raises(RuntimeError, match="not reentrant"):
                async with handle:
                    pass

        assert first.closed

        async with handle as second:
            assert second.read() == "data"

        assert second.closed

    @async_test
    async def test_relative_path_starting_with_http_is_local(
        self, tmp_path, monkeypatch
    ):
        (tmp_path / "http_fixture.csv").write_text("a,b")
        monkeypatch.chdir(tmp_path)

        async with async_url_open("http_fixture.csv") as f:
            assert f.read() == "a,b"

    @pytest.mark.simulated_network
    @pytest.mark.xfail(
        strict=True,
        reason="async_url_open ignores the Content-Type and decodes as utf-8",
    )
    @async_test
    async def test_async_url_open_honors_content_type_charset(self):
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
    async def test_sync_and_async_decode_line_endings_alike(self):
        """Decode carriage returns the same way in sync and async reads."""
        body = b"abc\rdef\n"
        sync_result = reencode(BytesIO(body), decode=True).read()

        with loopback_url(body, content_type="text/plain", path="p.txt") as url:
            async with async_url_open(url) as f:
                assert sync_result == f.read()


PARTIAL_READS = [
    pytest.param(b"abc\nde\n", False, list, [b"c\n", b"de\n"], id="bytes-iter"),
    pytest.param(b"abc\nde\n", False, bytes, b"c\nde\n", id="bytes-buffer"),
    pytest.param("abc\nde\n", True, list, ["c\n", "de\n"], id="text-iter"),
]


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

    @pytest.mark.parametrize(("source", "decode", "consume", "expected"), PARTIAL_READS)
    def test_partial_read_keeps_the_rest(self, source, decode, consume, expected):
        """Iterating or buffering after a sized read resumes where the read stopped."""
        f = BytesIO(source) if isinstance(source, bytes) else StringIO(source)
        reader = reencode(f, decode=decode)
        reader.read(2)
        assert consume(reader) == expected

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

    @pytest.mark.parametrize(
        ("kwargs", "expected"),
        [
            ({"decode": True}, "﻿<r/>\n"),
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

    def test_readline_without_ends_resumes_at_the_next_line(self):
        data = b"line one\nline two\nline three\n"
        full = reencode(BytesIO(data), decode=True).readlines(keepends=False)
        reader = reencode(BytesIO(data), decode=True)
        head, rest = reader.readline(keepends=False), reader.readlines(keepends=False)

        assert head == "line one"
        assert rest == ["line two", "line three"]
        assert [head] + rest == full

    def test_readline_resumes_after_a_partial_read(self):
        reader = reencode(BytesIO(b"line one\nline two\nline three\n"), decode=True)
        reader.read(1)

        assert reader.readline() == "ine one\n"
        assert reader.readlines() == ["line two\n", "line three\n"]

    def test_failed_open_closes_the_source(self):
        """A source that fails while the reader is being opened is closed."""

        class BrokenSource(BytesIO):
            def __next__(self):
                raise OSError("unreadable")

        source = BrokenSource(b"<r/>")

        with pytest.raises(OSError, match="unreadable"):
            reencode(source, decode=True)

        assert source.closed


class TestConversionFuncs:
    """The ``export`` converter registry mirrors ``Formats`` and drives ``export``."""

    def test_encoding_reaches_a_converter_that_takes_it(self, monkeypatch, tmp_path):
        encodings = []

        def records2csv(items: Items, encoding: str = "utf-8") -> StringIO:
            encodings.append(encoding)
            return StringIO("x\n")

        monkeypatch.setitem(CONVERSION_FUNCS, Formats.CSV, records2csv)
        export([{"x": 1}], "csv", str(tmp_path / "out.csv"), encoding="utf-16")
        assert encodings == ["utf-16"]

    def test_names_the_missing_extra(self, monkeypatch):
        monkeypatch.delitem(CONVERSION_FUNCS, Formats.OFX, raising=False)

        with pytest.raises(ValueError, match="requires the finance extra"):
            export([{"x": 1}], "ofx")


FILE_CHUNKS = [
    pytest.param("w+", "abcdef\nxy\n", ["abc", "def", "\nxy", "\n"], id="text"),
    pytest.param("wb+", b"abcdef", [b"abc", b"def"], id="binary"),
]


class TestChunkContent:
    """``_chunk_content`` splits a real file by ``chunksize``, like an in-memory one."""

    @pytest.mark.parametrize(("mode", "data", "expected"), FILE_CHUNKS)
    def test_real_file_honors_chunksize(self, tmp_path, mode, data, expected):
        with (tmp_path / "in").open(mode) as f:
            f.write(data)
            f.seek(0)
            assert list(_chunk_content(f, 3)) == expected


def _budgeted_probe() -> tuple[dict[str, int], Callable[[int], Awaitable[int]]]:
    state = {"current": 0, "peak": 0}

    async def leaf(x: int) -> int:
        state["current"] += 1
        state["peak"] = max(state["peak"], state["current"])
        await async_sleep(0.01)
        state["current"] -= 1
        return x

    return state, leaf


async def _forever(closed: list[bool]):
    index = 0

    try:
        while True:
            yield index
            index += 1
    finally:
        closed.append(True)


STREAM_OPTION_REJECTIONS = [
    pytest.param({"limit": 0}, "limit must be at least 1", id="limit"),
    pytest.param({"buffer": -1}, "buffer cannot be negative", id="buffer"),
]


class TestAsyncMapStream:
    """
    Test the bounded-memory async map streams.

    ``async_map_stream`` is concurrent, order-independent, and bounded-memory;
    ``async_map_ordered_stream`` keeps the same bound while preserving source order.
    """

    @skipif_issync
    @pytest.mark.parametrize(
        "stream",
        [
            pytest.param(async_map_stream, id="unordered"),
            pytest.param(async_map_ordered_stream, id="ordered"),
        ],
    )
    def test_empty_source_yields_nothing(self, stream):
        assert aresolve(stream(_double, [], limit=4)) == []

    @skipif_issync
    def test_accepts_async_source(self):
        async def gen():
            for i in range(5):
                yield i

        results = aresolve(async_map_stream(_double, gen(), limit=2))
        assert sorted(results) == [0, 2, 4, 6, 8]

    @pytest.mark.parametrize(
        ("stream", "bound"),
        [
            pytest.param(async_map_stream, 3 + 2 + 2, id="unordered"),
            pytest.param(async_map_ordered_stream, 2 * (3 + 2), id="ordered"),
        ],
    )
    @async_test
    async def test_backpressure_bounds_inflight(self, stream, bound):
        """An unbounded-ish source with a slow consumer must not run far ahead."""
        total = 200
        produced = 0

        async def gen():
            nonlocal produced
            for i in range(total):
                produced += 1
                yield i

        seen = 0

        async for _ in stream(_double, gen(), limit=3, buffer=2):
            seen += 1
            assert produced - seen <= bound
            await lowlevel.checkpoint()

        assert produced == total == seen

    @skipif_issync
    def test_ordered_preserves_source_order_under_skew(self):
        """The slowest item is first, so an unordered map would reorder it."""

        async def slow_first(i: int) -> int:
            await async_sleep((5 - i) * 0.01)
            return i

        result = aresolve(async_map_ordered_stream(slow_first, range(6), limit=3))
        assert result == list(range(6))

    @async_test
    async def test_shared_budget_caps_nested_fanout(self):
        """
        Share one concurrency budget across leaf maps.

        An outer fan-out of 4 items, each with 5 leaf operations, has 20 potential
        operations but never exceeds a budget of 3. The outer fan-out remains
        unbudgeted to avoid deadlock.
        """
        state, leaf = _budgeted_probe()
        budget = Semaphore(3)

        async def source(i: int) -> list[int]:
            leaves = async_map_stream(leaf, range(5), limit=10, budget=budget)
            return [r async for r in leaves]

        outer = async_map_stream(source, range(4), limit=10)
        results = [r async for r in outer]
        assert len(results) == 4
        assert state["peak"] <= 3

    @pytest.mark.parametrize(
        ("stream", "arrange"),
        [
            pytest.param(async_map_stream, sorted, id="unordered"),
            pytest.param(async_map_ordered_stream, list, id="ordered"),
        ],
    )
    @async_test
    async def test_shared_budget_caps_concurrent_streams(self, stream, arrange):
        """Two concurrent maps sharing a budget of 3 never exceed it."""
        state, leaf = _budgeted_probe()
        budget = Semaphore(3)

        async def collect() -> list[int]:
            mapped = stream(leaf, range(10), limit=4, budget=budget)
            return [r async for r in mapped]

        results = await gather_results([collect(), collect()])
        assert [arrange(result) for result in results] == [list(range(10))] * 2
        assert 1 < state["peak"] <= 3

    @pytest.mark.parametrize(
        ("stream", "firsts"),
        [
            pytest.param(async_map_stream, {0, 2}, id="unordered"),
            pytest.param(async_map_ordered_stream, {0}, id="ordered"),
        ],
    )
    @async_test
    async def test_early_close_stops_workers_and_closes_source(self, stream, firsts):
        closed: list[bool] = []
        mapped = stream(_double, _forever(closed), limit=2)
        first = await anext(mapped)
        await mapped.aclose()
        assert first in firsts
        assert closed == [True]

    @skipif_issync
    @pytest.mark.parametrize(
        "build", [_MAP, _ORDERED, _MERGE], ids=["map", "ordered", "merge"]
    )
    @pytest.mark.parametrize(("kwargs", "match"), STREAM_OPTION_REJECTIONS)
    def test_rejects_bad_limit_or_buffer(self, build, kwargs, match):
        with pytest.raises(ValueError, match=match):
            aresolve(build(**kwargs))

    @pytest.mark.xfail(
        strict=True,
        reason="sliding-window async ordered mapping is not yet implemented",
    )
    @async_test
    async def test_ordered_yields_ready_results_while_a_later_item_runs(self):
        """A slow second item never holds back the first result or the third start."""
        log: list[str] = []

        async def slow_second(i: int) -> int:
            log.append(f"start {i}")
            await async_sleep(0.05 if i == 1 else 0)
            log.append(f"done {i}")
            return i

        async for i in async_map_ordered_stream(slow_second, range(4), limit=2):
            log.append(f"yield {i}")

        assert log.index("yield 0") < log.index("done 1")
        assert log.index("start 2") < log.index("done 1")


async def _gen_items(items, delay=0.0):
    for item in items:
        if delay:
            await async_sleep(delay)

        yield item


class TestAsyncMerge:
    @skipif_issync
    def test_async_merge_yields_every_value(self):
        """More iterables than ``limit`` still merge in full."""
        iterables = [_gen_items([1, 2]), _gen_items([3, 4]), _gen_items([5])]
        assert sorted(aresolve(async_merge(iterables, limit=2))) == [1, 2, 3, 4, 5]

    @async_test
    async def test_async_merge_interleaves_across_iterables(self):
        """A fast iterable's items surface before a slow one finishes (incremental)."""
        slow = _gen_items(["slow1", "slow2"], delay=0.05)
        fast = _gen_items(["fast1", "fast2"])
        out = [item async for item in async_merge([slow, fast], limit=2)]
        assert sorted(out) == ["fast1", "fast2", "slow1", "slow2"]
        assert out.index("fast2") < out.index("slow2")


class TestGatherResults:
    @async_test
    async def test_gather_results_preserves_none_positions(self):
        """A legitimate ``None`` result stays in place; output aligns with inputs."""
        awaitables = [async_return(None), async_return(1), async_return(None)]
        result = await gather_results(awaitables)
        assert result == [None, 1, None]


class TestCapabilityFlags:
    """
    Pin the parser capability flags with and without each perf lib installed.

    These run unmarked in every environment, so the base environment verifies the
    degraded behavior rather than skipping the extra-only tests.
    """

    def test_capability_flags_track_installed_libs(self):
        """The parser capability flags reflect whether each perf lib is importable."""
        assert IS_LXML is is_installed("lxml")
        assert IS_FASTFEEDPARSER is is_installed("fastfeedparser")

        if not is_installed("ijson"):
            assert IJSON_IS_NATIVE is False


class TestRegisterTarget:
    def test_entry_point_loads_a_target_class(self) -> None:
        ep = EntryPoint("file", "riko.definitions._targets:FileTarget", "riko.targets")
        assert TargetRegistry()._load(ep) is FileTarget

    def test_entry_point_must_load_a_target_class(self) -> None:
        ep = EntryPoint("bogus", "builtins:len", "riko.targets")

        with pytest.raises(TypeError, match="must load a target class"):
            TargetRegistry()._load(ep)

    def test_entry_point_key_must_match_the_backend(self, monkeypatch) -> None:
        ep = EntryPoint("s3", "riko.definitions._targets:FileTarget", "riko.targets")
        monkeypatch.setattr("riko.runtime._registry.entry_points", lambda group: [ep])

        with pytest.raises(ValueError, match="'s3' declares a target named 'file'"):
            TargetRegistry()._load_entry_point("s3")


class TestConverterPath:
    """The native whole-stream path and the temporary singleton path."""

    def _spy(self, monkeypatch):
        calls = []
        original = _write_session.serialize_items

        def spy(items, fmt, **kwargs):
            materialized = list(items)
            calls.append(materialized)
            return original(materialized, fmt, **kwargs)

        monkeypatch.setattr(_write_session, "serialize_items", spy)
        return calls

    def test_sink_converts_whole_stream_once(self, monkeypatch, tmp_path):
        calls = self._spy(monkeypatch)
        _sink(ITEMS, tmp_path / "out.jsonl")

        assert len(calls) == 1
        assert calls[0] == ITEMS

    def test_passthrough_converts_per_item(self, monkeypatch, tmp_path):
        calls = self._spy(monkeypatch)
        prepared = build_write(tmp_path / "out.jsonl")
        yielded = list(write_through(ITEMS, prepared, terminating=_never))

        assert yielded == ITEMS
        assert len(calls) == len(ITEMS)


CSV_SINK_CASES = [
    pytest.param(None, ITEMS, "replace", _CSV012, id="csv-replace-header-once"),
    pytest.param(None, _X0, "append", _CSV0, id="csv-append-to-empty-emits-header"),
    pytest.param(b"x\r\n0", _X1, "append", b"x\r\n0\n1\r\n", id="csv-unterminated"),
    pytest.param(_CSV0, [], "append", _CSV0, id="csv-empty-append-unchanged"),
    pytest.param(_CSV0, _X1, "append", b"x\r\n0\r\n1\r\n", id="csv-append-no-header"),
]


class TestCsv:
    @pytest.mark.parametrize(("seed", "items", "mode", "expected"), CSV_SINK_CASES)
    def test_sink_writes_expected_bytes(self, tmp_path, seed, items, mode, expected):
        path = tmp_path / "out.csv"
        if seed is not None:
            path.write_bytes(seed)

        _sink(items, path, mode)
        assert path.read_bytes() == expected

    def test_passthrough_singleton_preserves_schema(self, tmp_path):
        path = tmp_path / "out.csv"
        rows = [{"a": 1, "b": 2}, {"b": 4, "a": 3}]
        list(write_through(rows, build_write(path), terminating=_never))
        assert path.read_bytes() == b"a,b\r\n1,2\r\n3,4\r\n"

    def test_passthrough_unexpected_field_raises(self, tmp_path):
        path = tmp_path / "out.csv"
        rows = [{"a": 1}, {"a": 2, "b": 3}]

        with pytest.raises(ValueError, match="not in the CSV header"):
            list(write_through(rows, build_write(path), terminating=_never))


JSONL_APPEND_CASES = [
    pytest.param(_JSON0, _X1, _JSON01, id="jsonl-append-terminated"),
    pytest.param(b'{"x": 0}', _X1, _JSON01, id="jsonl-append-unterminated"),
    pytest.param(_JSON0, [], _JSON0, id="jsonl-empty-append-unchanged"),
]


class TestJsonl:
    def test_singleton_has_no_array(self, tmp_path):
        path = tmp_path / "out.jsonl"
        list(write_through(ITEMS, build_write(path), terminating=_never))
        assert path.read_bytes() == b'{"x": 0}\n{"x": 1}\n{"x": 2}\n'

    @pytest.mark.parametrize(("seed", "items", "expected"), JSONL_APPEND_CASES)
    def test_append_writes_expected_bytes(self, tmp_path, seed, items, expected):
        path = tmp_path / "out.jsonl"
        path.write_bytes(seed)
        _sink(items, path, "append")
        assert path.read_bytes() == expected


class TestFramed:
    def test_passthrough_buffers_until_finalize(self, tmp_path):
        path = tmp_path / "out.json"
        stream = write_through(ITEMS, build_write(path), terminating=_never)
        first = next(stream)
        assert not path.exists()
        assert [first, *stream] == ITEMS
        assert path.read_bytes() == b'[{"x": 0}, {"x": 1}, {"x": 2}]'

    def test_sink_writes_one_document(self, tmp_path):
        path = tmp_path / "out.json"
        result = _sink(ITEMS, path)
        assert isinstance(result, WriteResult)
        assert result.written > 0
        assert path.read_bytes() == b'[{"x": 0}, {"x": 1}, {"x": 2}]'

    def test_abort_discards_staged_document(self, tmp_path):
        path = tmp_path / "out.json"
        prepared = build_write(path)

        with file_write_session(prepared) as session:
            session.write(ITEMS)
            session.abort()

        assert not path.exists()

    @ATOMIC_PUBLICATION_PENDING
    def test_interrupted_finalize_keeps_original_content(self, tmp_path, monkeypatch):
        # The commit empties the destination on open, so an interruption before the
        # document is written loses the old content instead of leaving it in place.
        path = tmp_path / "out.json"
        path.write_bytes(b'[{"x": 9}]')

        def interrupt(_content):
            raise RuntimeError("interrupted")

        monkeypatch.setattr(_write_session, "_cast_bytes", interrupt)

        with file_write_session(build_write(path)) as session:
            session.write(ITEMS)

            with pytest.raises(RuntimeError, match="interrupted"):
                session.finalize()

        assert path.read_bytes() == b'[{"x": 9}]'


class TestSessionLifecycle:
    def _session(self, tmp_path, name="out.json"):
        session = _SyncFileWriteSession(build_write(tmp_path / name))
        session.acquire()
        return session

    def test_open_to_finalized(self, tmp_path):
        session = self._session(tmp_path)
        session.write(ITEMS)
        session.finalize()
        assert session._state is _SessionState.FINALIZED
        session.close()

    def test_open_to_aborted(self, tmp_path):
        session = self._session(tmp_path)
        session.abort()
        assert session._state is _SessionState.ABORTED
        session.close()

    def test_write_after_finalize_rejected(self, tmp_path):
        session = self._session(tmp_path)
        session.write(ITEMS)
        session.finalize()

        with pytest.raises(
            PipelineStateError, match="the write session in state 'finalized'"
        ):
            session.write(ITEMS)

        session.close()

    def test_write_after_abort_rejected(self, tmp_path):
        session = self._session(tmp_path)
        session.abort()

        with pytest.raises(PipelineStateError, match="aborted"):
            session.write(ITEMS)

        session.close()

    def test_close_twice_is_safe(self, tmp_path):
        session = self._session(tmp_path)
        session.close()
        session.close()

    def test_close_never_commits(self, tmp_path):
        path = tmp_path / "out.json"
        session = _SyncFileWriteSession(build_write(path))
        session.acquire()
        session.write(ITEMS)
        session.close()
        assert not path.exists()

    def test_incremental_abort_keeps_written_bytes(self, tmp_path):
        path = tmp_path / "out.jsonl"
        session = _SyncFileWriteSession(build_write(path))
        session.acquire()
        session.write({"x": 1})
        session.abort()
        session.close()
        assert path.read_bytes() == b'{"x": 1}\n'

    def test_stream_then_item_rejected(self, tmp_path):
        session = self._session(tmp_path)
        session.write(ITEMS)

        with pytest.raises(PipelineStateError, match="cannot mix item and stream"):
            session.write({"x": 0})

        session.close()

    def test_item_then_stream_rejected(self, tmp_path):
        session = self._session(tmp_path)
        session.write({"x": 0})

        with pytest.raises(PipelineStateError, match="cannot mix item and stream"):
            session.write(ITEMS)

        session.close()

    def test_two_whole_streams_rejected(self, tmp_path):
        session = self._session(tmp_path)
        session.write(ITEMS)

        with pytest.raises(PipelineStateError, match="cannot attempt multiple stream"):
            session.write(ITEMS)

        session.close()


class TestWriteExecution:
    def test_writes_mid_chain(self, tmp_path):
        path = tmp_path / "out.json"
        stream = write_through(ITEMS, build_write(path), terminating=_never)
        assert list(tail(stream, conf={"count": 1})) == [{"x": 2}]
        assert path.read_bytes() == b'[{"x": 0}, {"x": 1}, {"x": 2}]'

    def test_replace_defers_truncation_until_consumed(self, tmp_path):
        path = tmp_path / "out.jsonl"
        path.write_bytes(b'{"old": 1}\n')
        prepared = build_write(path, "replace")
        stream = write_through(ITEMS, prepared, terminating=_never)
        assert path.read_bytes() == b'{"old": 1}\n'
        list(stream)
        assert path.read_bytes() == b'{"x": 0}\n{"x": 1}\n{"x": 2}\n'

    def test_graceful_close_finalizes_prefix(self, tmp_path):
        path = tmp_path / "out.json"
        stream = write_through(ITEMS, build_write(path), terminating=_never)
        next(stream)
        stream.close()
        assert path.read_bytes() == b'[{"x": 0}]'

    def test_terminate_aborts(self, tmp_path):
        path = tmp_path / "out.json"
        stream = write_through(ITEMS, build_write(path), terminating=_always)
        next(stream)
        stream.close()
        assert not path.exists()

    def test_exception_aborts(self, tmp_path):
        path = tmp_path / "out.json"
        stream = write_through(ITEMS, build_write(path), terminating=_never)
        next(stream)

        with pytest.raises(RuntimeError, match="boom"):
            stream.throw(RuntimeError("boom"))

        assert not path.exists()

    @ATOMIC_PUBLICATION_PENDING
    @pytest.mark.parametrize(
        ("name", "original"), [("out.csv", b"a\n1\n"), ("out.jsonl", b'{"a": 1}\n')]
    )
    def test_failed_replace_keeps_original_content(self, tmp_path, name, original):
        path = tmp_path / name
        path.write_bytes(original)

        def source() -> Iterator[dict[str, int]]:
            yield {"a": 2}
            raise ValueError("boom")

        stream = write_through(source(), build_write(path), terminating=_never)

        with pytest.raises(ValueError, match="boom"):
            list(stream)

        assert path.read_bytes() == original


async def _asink(
    items: Feed, dest: PathLike, mode: str = "replace", **kwargs
) -> WriteResult:
    """Delivers the whole stream to *dest* and commits it, as a terminal write does."""
    async with async_file_write_session(build_write(dest, mode, **kwargs)) as session:
        await session.awrite(items)
        result = await session.afinalize()

    return result


@skipif_issync
class TestAsyncWriteExecution:
    @async_test
    async def test_passthrough_preserves_stream(self, tmp_path):
        prepared = build_write(tmp_path / "out.json")
        stream = awrite_through(as_async(ITEMS), prepared, terminating=_never)
        assert [item async for item in stream] == ITEMS

    @async_test
    async def test_writes_mid_chain(self, tmp_path):
        path = tmp_path / "out.json"
        stream = awrite_through(as_async(ITEMS), build_write(path), terminating=_never)
        tailed = async_tail(stream, conf={"count": 1})
        assert [item async for item in tailed] == [{"x": 2}]
        assert path.read_bytes() == b'[{"x": 0}, {"x": 1}, {"x": 2}]'

    @async_test
    async def test_csv_singleton_preserves_schema(self, tmp_path):
        path = tmp_path / "out.csv"
        rows = [{"a": 1, "b": 2}, {"b": 4, "a": 3}]
        stream = awrite_through(as_async(rows), build_write(path), terminating=_never)
        _ = [item async for item in stream]
        assert path.read_bytes() == b"a,b\r\n1,2\r\n3,4\r\n"

    @async_test
    async def test_graceful_close_finalizes_prefix(self, tmp_path):
        path = tmp_path / "out.json"
        stream = awrite_through(as_async(ITEMS), build_write(path), terminating=_never)
        await anext(stream)
        await stream.aclose()
        assert path.read_bytes() == b'[{"x": 0}]'

    @async_test
    async def test_terminate_aborts(self, tmp_path):
        path = tmp_path / "out.json"
        stream = awrite_through(as_async(ITEMS), build_write(path), terminating=_always)
        await anext(stream)
        await stream.aclose()
        assert not path.exists()

    @async_test
    async def test_exception_aborts(self, tmp_path):
        path = tmp_path / "out.json"
        stream = awrite_through(as_async(ITEMS), build_write(path), terminating=_never)
        await anext(stream)

        with pytest.raises(RuntimeError, match="boom"):
            await stream.athrow(RuntimeError("boom"))

        assert not path.exists()

    @async_test
    async def test_whole_stream_writes_one_document(self, tmp_path):
        path = tmp_path / "out.json"
        result = await _asink(ITEMS, path)
        assert result.written > 0
        assert path.read_bytes() == b'[{"x": 0}, {"x": 1}, {"x": 2}]'


class TestSink:
    def test_non_file_target_execution_unsupported(self):
        prepared = build_write(RecordStore(), "replace")

        with (
            pytest.raises(UnsupportedTargetError, match="RecordStore"),
            file_write_session(prepared),
        ):
            pass  # pragma: no cover
