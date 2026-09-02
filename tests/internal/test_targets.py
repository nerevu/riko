# vim: sw=4:ts=4:expandtab
"""
Tests the sink target adapters and the ``write``/``sink`` verbs (``riko.targets``).

Covers ``File`` serialization (sync + async), capability-aware ``build_write``
validation, destination/format resolution, the format-aware ``file_writer``
(stream vs. buffer), and the collection ``write``/``sink`` surface end to end.
"""

from dataclasses import dataclass

import pytest

from riko._pubsub import reset_pubsub
from riko.bado._backend import run
from riko.collections import AsyncPipe, SyncPipe
from riko.sinks import SinkMode, SinkWrite
from riko.targets import (
    File,
    SinkCapabilities,
    SinkResult,
    build_write,
    file_writer,
    resolve_format,
    resolve_target,
)
from tests import skipif_issync

ITEMS = [{"x": 0}, {"x": 1}, {"x": 2}]


@pytest.fixture(autouse=True)
def _isolate_pubsub():
    reset_pubsub()
    yield
    reset_pubsub()


@dataclass(frozen=True)
class _RecordStore:
    """A non-serializing keyed target, for the record-store ``build_write`` branch."""

    def capabilities(self) -> SinkCapabilities:
        return SinkCapabilities(modes=frozenset(SinkMode), serializes=False)

    def deliver(self, records, write, *, fmt=None) -> SinkResult:
        return SinkResult(created=len(list(records)))

    async def adeliver(self, records, write, *, fmt=None) -> SinkResult:
        return self.deliver(records, write, fmt=fmt)


class TestResolveTarget:
    def test_path_string_becomes_file(self):
        assert resolve_target("out.csv") == File("out.csv")

    def test_sink_target_passes_through(self):
        target = File("out.json")
        assert resolve_target(target) is target

    def test_non_target_raises(self):
        with pytest.raises(TypeError, match="cannot resolve"):
            resolve_target(42)  # pyright: ignore[reportArgumentType]


class TestResolveFormat:
    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("out.csv", "csv"),
            ("out.jsonl", "jsonl"),
            ("out.txt", "json"),
            ("out", "json"),
        ],
    )
    def test_infers_from_extension(self, url, expected):
        assert resolve_format(url, None) == expected

    def test_explicit_format_wins(self):
        assert resolve_format("out.csv", "json") == "json"


class TestBuildWrite:
    def test_file_forbids_keys(self):
        with pytest.raises(ValueError, match="forbids 'keys'"):
            build_write(File("out.csv"), "append", keys="id")

    def test_file_unsupported_mode(self):
        with pytest.raises(ValueError, match="does not support the 'merge'"):
            build_write(File("out.csv"), "merge")

    def test_record_store_routes_through_sink_write(self):
        spec = build_write(_RecordStore(), "merge", keys="endpoint_id")

        assert spec.mode is SinkMode.MERGE
        assert spec.keys == ("endpoint_id",)

    def test_record_store_missing_keys_rejected(self):
        with pytest.raises(ValueError, match="requires 'keys'"):
            build_write(_RecordStore(), "merge")


class TestFileDeliver:
    def test_replace_writes_document(self, tmp_path):
        path = tmp_path / "out.json"
        result = File(str(path)).deliver(ITEMS, SinkWrite(SinkMode.REPLACE))

        assert result.written > 0
        assert path.read_bytes() == b'[{"x": 0}, {"x": 1}, {"x": 2}]'

    def test_append_extends(self, tmp_path):
        path = tmp_path / "out.json"
        File(str(path)).deliver([{"x": 0}], SinkWrite(SinkMode.APPEND))
        File(str(path)).deliver([{"x": 1}], SinkWrite(SinkMode.APPEND))

        assert path.read_bytes() == b'[{"x": 0}][{"x": 1}]'

    @skipif_issync
    def test_adeliver_matches_deliver(self, tmp_path):
        path = tmp_path / "out.json"

        async def main():
            return await File(str(path)).adeliver(ITEMS, SinkWrite(SinkMode.REPLACE))

        result = run(main)
        assert result.written > 0
        assert path.read_bytes() == b'[{"x": 0}, {"x": 1}, {"x": 2}]'


class TestFileWriter:
    @pytest.mark.parametrize(
        ("dest", "streams"),
        [("out.csv", True), ("out.jsonl", True), ("out.json", False), ("out", False)],
    )
    def test_streamability_inferred_from_extension(self, dest, streams):
        assert file_writer(dest).stream is streams

    @pytest.mark.parametrize("override", [True, False])
    def test_stream_override(self, override):
        assert file_writer("out.json", stream=override).stream is override

    def test_keyed_mode_rejected(self):
        with pytest.raises(ValueError, match="append, replace"):
            file_writer("out.csv", mode="merge")


class TestSyncWrite:
    def test_passthrough_preserves_stream(self, tmp_path):
        flow = SyncPipe(source=ITEMS).write(str(tmp_path / "out.json"))
        assert list(flow) == ITEMS

    def test_buffered_flushes_on_completion(self, tmp_path):
        path = tmp_path / "out.json"
        list(SyncPipe(source=ITEMS).write(str(path)))
        assert path.read_bytes() == b'[{"x": 0}, {"x": 1}, {"x": 2}]'

    def test_buffered_not_written_before_completion(self, tmp_path):
        path = tmp_path / "out.json"
        flow = SyncPipe(source=ITEMS).write(str(path))
        next(flow)
        assert not path.exists() or path.read_bytes() == b""

    def test_streaming_jsonl_is_incremental(self, tmp_path):
        path = tmp_path / "out.jsonl"
        list(SyncPipe(source=ITEMS).write(str(path)))
        assert path.read_bytes() == b'{"x": 0}\n{"x": 1}\n{"x": 2}\n'

    def test_streaming_csv_writes_header_once(self, tmp_path):
        path = tmp_path / "out.csv"
        list(SyncPipe(source=ITEMS).write(str(path)))
        assert path.read_bytes() == b"x\r\n0\r\n1\r\n2\r\n"

    def test_writes_mid_chain(self, tmp_path):
        path = tmp_path / "out.json"
        result = SyncPipe(source=ITEMS).write(str(path)).pipe("tail", conf={"count": 1})
        assert list(result) == [{"x": 2}]
        assert path.read_bytes() == b'[{"x": 0}, {"x": 1}, {"x": 2}]'

    def test_graceful_close_flushes_partial(self, tmp_path):
        path = tmp_path / "out.json"
        flow = SyncPipe(source=ITEMS).write(str(path))
        next(flow)
        flow.close()
        assert path.read_bytes().startswith(b"[")

    def test_graceful_context_exit_flushes(self, tmp_path):
        path = tmp_path / "out.json"
        with SyncPipe(source=ITEMS).write(str(path)) as flow:
            next(flow)
        assert path.read_bytes().startswith(b"[")

    def test_terminate_discards_buffer(self, tmp_path):
        path = tmp_path / "out.json"
        flow = SyncPipe(source=ITEMS).write(str(path))
        next(flow)
        flow.terminate()
        assert not path.exists()

    def test_exceptional_context_exit_discards(self, tmp_path):
        path = tmp_path / "out.json"

        def boom():
            with SyncPipe(source=ITEMS).write(str(path)) as flow:
                next(flow)
                raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            boom()

        assert not path.exists()


class TestSink:
    def test_terminal_returns_result(self, tmp_path):
        path = tmp_path / "out.json"
        result = SyncPipe(source=ITEMS).sink(str(path), mode="replace")

        assert isinstance(result, SinkResult)
        assert result.written > 0
        assert path.read_bytes() == b'[{"x": 0}, {"x": 1}, {"x": 2}]'

    def test_file_rejects_keys(self, tmp_path):
        with pytest.raises(ValueError, match="forbids 'keys'"):
            SyncPipe(source=ITEMS).sink(str(tmp_path / "out.csv"), keys="x")

    @skipif_issync
    def test_async_sink(self, tmp_path):
        path = tmp_path / "out.json"

        async def main():
            return await AsyncPipe(source=ITEMS).sink(str(path), mode="replace")

        result = run(main)
        assert result.written > 0
        assert path.read_bytes() == b'[{"x": 0}, {"x": 1}, {"x": 2}]'


class TestAsyncWriteUnsupported:
    def test_async_pipe_write_raises(self):
        with pytest.raises(NotImplementedError, match="async write"):
            AsyncPipe(source=ITEMS).write("out.json")
