# vim: sw=4:ts=4:expandtab
"""Provides internal tests for URL/file I/O, re-encoding, and async stream helpers."""

from __future__ import annotations

from io import BytesIO
from os import linesep
from time import monotonic
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import Mock, patch
from urllib.response import addinfourl

import pytest
from requests import Response

from riko.bado._backend import Semaphore, async_sleep, lowlevel
from riko.bado._util import async_return, gather_results
from riko.bado.itertools import (
    async_map,
    async_map_ordered_stream,
    async_map_stream,
    async_merge,
)
from riko.base._paths import get_path
from riko.coercion._configs import CsvObjconf
from riko.io._async import async_url_open
from riko.io._reencode import Reencoder, reencode
from riko.io._serialization import CONVERSION_FUNCS
from riko.io._sync import Fetch
from riko.modules import csv
from riko.modules.timeout import AsyncTimeoutIterator
from riko.types._enums import Formats
from tests import aresolve, async_test, skipif_issync
from tests._loopback import loopback_url

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


async def _double(x: int) -> int:
    return x * 2


class TestFetch:
    def test_csv_headerless_closes_original_source(self, monkeypatch):
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
class TestLoopbackServer:
    """
    The streamed/memoized branches exercised against a real loopback server.

    The streamed and memoized branches only diverge once bytes actually cross a
    socket, so a fixture file cannot exercise them: the streamed text branch reads
    ``r.raw``, which is empty unless the request was made with ``stream=True``.
    """

    BODY = "".join(f"line {index} ünïcode\n" for index in range(2000))
    PAYLOAD = BODY.encode()

    @pytest.fixture(scope="class")
    @classmethod
    def url(cls):
        with loopback_url(cls.BODY) as served:
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


class TestAsyncUrlOpen:
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


URL = "https://example.test/data"


def _async_get(content, content_type):
    async def async_get(url, **_):
        return SimpleNamespace(content=content, headers={"content-type": content_type})

    return async_get


@skipif_issync
class TestExtensionlessAsyncUrlOpen:
    """``async_url_open`` exposes an ``ext`` derived from the content type."""

    @pytest.mark.parametrize(
        ("content_type", "expected"),
        [
            ("application/json; charset=utf-8", "json"),
            ("text/xml", "xml"),
            ("text/html", "html"),
        ],
    )
    @pytest.mark.anyio
    async def test_ext_from_content_type(self, monkeypatch, content_type, expected):
        monkeypatch.setattr("riko.io._async.async_get", _async_get(b"{}", content_type))
        f = await async_url_open(URL)
        assert f.ext == expected
        assert f.content_type == content_type


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


class TestConversionFuncs:
    """``Formats`` members mirror the ``export`` converters."""

    def test_every_converter_has_a_member(self):
        assert set(CONVERSION_FUNCS) <= set(Formats)


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


class TestAsyncMapStream:
    """
    Test the bounded-memory async map streams.

    ``async_map_stream`` is concurrent, order-independent, and bounded-memory;
    ``async_map_ordered_stream`` keeps the same bound while preserving source order.
    """

    @skipif_issync
    def test_maps_all_items_order_independent(self):
        results = aresolve(async_map_stream(_double, range(10), limit=4))
        assert sorted(results) == [x * 2 for x in range(10)]

    @skipif_issync
    def test_empty_source_yields_nothing(self):
        assert aresolve(async_map_stream(_double, [], limit=4)) == []

    @skipif_issync
    def test_accepts_async_source(self):
        async def gen():
            for i in range(5):
                yield i

        results = aresolve(async_map_stream(_double, gen(), limit=2))
        assert sorted(results) == [0, 2, 4, 6, 8]

    @async_test
    async def test_backpressure_bounds_inflight(self):
        """An unbounded-ish source with a slow consumer must not run far ahead."""
        limit, buffer, total = 3, 2, 200
        produced = 0

        async def gen():
            nonlocal produced
            for i in range(total):
                produced += 1
                yield i

        seen = 0

        async for _ in async_map_stream(_double, gen(), limit=limit, buffer=buffer):
            seen += 1
            assert produced - seen <= limit + buffer + 2
            await lowlevel.checkpoint()

        assert produced == total
        assert seen == total

    @skipif_issync
    def test_ordered_preserves_source_order_under_skew(self):
        """The slowest item is first, so an unordered map would reorder it."""

        async def slow_first(i: int) -> int:
            await async_sleep((5 - i) * 0.01)
            return i

        result = aresolve(async_map_ordered_stream(slow_first, range(6), limit=3))
        assert result == list(range(6))

    @skipif_issync
    def test_ordered_empty_source_yields_nothing(self):
        assert aresolve(async_map_ordered_stream(_double, [], limit=4)) == []

    @async_test
    async def test_ordered_backpressure_bounds_inflight(self):
        limit, buffer, total = 3, 2, 200
        produced = 0

        async def gen():
            nonlocal produced
            for i in range(total):
                produced += 1
                yield i

        seen = 0
        stream = async_map_ordered_stream(_double, gen(), limit=limit, buffer=buffer)

        async for _ in stream:
            seen += 1
            assert produced - seen <= 2 * (limit + buffer)
            await lowlevel.checkpoint()

        assert produced == total == seen

    @async_test
    async def test_shared_budget_caps_nested_fanout(self):
        """
        Share one concurrency budget across leaf maps.

        An outer fan-out of 4 items, each with 5 leaf operations, has 20 potential
        operations but never exceeds a budget of 3. The outer fan-out remains
        unbudgeted to avoid deadlock.
        """
        state = {"current": 0, "peak": 0}
        budget = Semaphore(3)

        async def leaf(x: int) -> int:
            state["current"] += 1
            state["peak"] = max(state["peak"], state["current"])
            await async_sleep(0.01)
            state["current"] -= 1
            return x

        async def source(i: int) -> list[int]:
            leaves = async_map_stream(leaf, range(5), limit=10, budget=budget)
            return [r async for r in leaves]

        outer = async_map_stream(source, range(4), limit=10)
        results = [r async for r in outer]
        assert len(results) == 4
        assert state["peak"] <= 3

    @async_test
    async def test_shared_budget_caps_concurrent_unordered_streams(self):
        """Two concurrent unordered maps sharing a budget of 3 never exceed it."""
        state, leaf = _budgeted_probe()
        budget = Semaphore(3)

        async def collect() -> list[int]:
            stream = async_map_stream(leaf, range(10), limit=4, budget=budget)
            return [r async for r in stream]

        results = await gather_results([collect(), collect()])
        assert [sorted(result) for result in results] == [list(range(10))] * 2
        assert 1 < state["peak"] <= 3

    @async_test
    async def test_shared_budget_caps_concurrent_ordered_streams(self):
        """Two concurrent ordered maps sharing a budget of 3 never exceed it."""
        state, leaf = _budgeted_probe()
        budget = Semaphore(3)

        async def collect() -> list[int]:
            stream = async_map_ordered_stream(leaf, range(10), limit=4, budget=budget)
            return [r async for r in stream]

        results = await gather_results([collect(), collect()])
        assert results == [list(range(10))] * 2
        assert 1 < state["peak"] <= 3

    @async_test
    async def test_async_map_stream_early_close_stops_workers_and_closes_source(self):
        closed: list[bool] = []
        stream = async_map_stream(_double, _forever(closed), limit=2)
        first = await anext(stream)
        await stream.aclose()
        assert first in {0, 2}
        assert closed == [True]

    @async_test
    async def test_async_map_ordered_stream_early_close_stops_workers_and_closes_source(
        self,
    ):
        closed: list[bool] = []
        stream = async_map_ordered_stream(_double, _forever(closed), limit=2)
        first = await anext(stream)
        await stream.aclose()
        assert first == 0
        assert closed == [True]

    @skipif_issync
    @pytest.mark.parametrize("stream", [async_map_stream, async_map_ordered_stream])
    def test_stream_rejects_bad_limit(self, stream):
        with pytest.raises(ValueError, match="limit must be at least 1"):
            aresolve(stream(_double, range(3), limit=0))

    @skipif_issync
    @pytest.mark.parametrize("stream", [async_map_stream, async_map_ordered_stream])
    def test_stream_rejects_negative_buffer(self, stream):
        with pytest.raises(ValueError, match="buffer cannot be negative"):
            aresolve(stream(_double, range(3), buffer=-1))


class TestAsyncMap:
    @async_test
    async def test_async_map_allows_no_limit(self):
        result = await async_map(_double, range(3), 0)
        assert result == [0, 2, 4]

    @async_test
    async def test_async_map_rejects_negative_limit(self):
        with pytest.raises(ValueError, match="limit cannot be negative"):
            await async_map(_double, range(3), -1)


async def _gen_items(items, delay=0.0):
    for item in items:
        if delay:
            await async_sleep(delay)

        yield item


class TestAsyncMerge:
    @skipif_issync
    def test_async_merge_yields_every_value(self):
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

    @skipif_issync
    def test_async_merge_rejects_bad_limit(self):
        with pytest.raises(ValueError, match="limit must be at least 1"):
            aresolve(async_merge([_gen_items([1])], limit=0))

    @skipif_issync
    def test_async_merge_rejects_negative_buffer(self):
        with pytest.raises(ValueError, match="buffer cannot be negative"):
            aresolve(async_merge([_gen_items([1])], buffer=-1))


class TestGatherResults:
    @async_test
    async def test_gather_results_preserves_none_positions(self):
        """A legitimate ``None`` result stays in place; output aligns with inputs."""
        awaitables = [async_return(None), async_return(1), async_return(None)]
        result = await gather_results(awaitables)
        assert result == [None, 1, None]


class TestAsyncTimeoutIterator:
    @pytest.mark.timeout(5)
    @pytest.mark.xfail(
        strict=True,
        reason="AsyncTimeoutIterator only checks its deadline between anexts. A "
        "source that stalls past the deadline is awaited to completion rather than "
        "interrupted.",
    )
    @async_test
    async def test_timeout_interrupts_a_stalled_source(self):
        """A stalled source is abandoned after timeout, not awaited to completion."""

        async def source():
            yield {"x": 0}
            await async_sleep(1.0)
            yield {"x": 1}

        it = AsyncTimeoutIterator(source(), timeout_ms=50)
        start = monotonic()
        [item async for item in it]
        run_time = monotonic() - start
        assert run_time < 0.5
