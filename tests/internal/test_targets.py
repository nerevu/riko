# vim: sw=4:ts=4:expandtab
"""
Tests the write target adapters and the ``write``/``sink`` verbs (``riko.targets``).

Covers ``File`` serialization (sync + async), capability-aware ``build_write``
validation, destination/format resolution, the format-aware ``file_writer``
(negotiated stream vs. buffer), and the collection ``write``/``sink`` surface end
to end.
"""

from dataclasses import dataclass

import pytest

from riko._pubsub import reset_pubsub
from riko.collections import AsyncPipe, SyncPipe
from riko.targets import (
    File,
    WriteCapabilities,
    WriteResult,
    build_write,
    file_writer,
    resolve_format,
    resolve_target,
)
from riko.writes import WriteMode, WriteOperation
from tests import async_test

ITEMS = [{"x": 0}, {"x": 1}, {"x": 2}]


@pytest.fixture(autouse=True)
def _isolate_pubsub():
    reset_pubsub()
    yield
    reset_pubsub()


@dataclass(frozen=True)
class _RecordStore:
    """A non-serializing keyed target, for the record-store ``build_write`` branch."""

    def capabilities(self, fmt=None) -> WriteCapabilities:
        return WriteCapabilities(modes=frozenset(WriteMode), serializes=False)

    def deliver(self, records, write, *, fmt=None) -> WriteResult:
        return WriteResult(created=len(list(records)))

    async def adeliver(self, records, write, *, fmt=None) -> WriteResult:
        return self.deliver(records, write, fmt=fmt)


class TestResolveTarget:
    def test_path_string_becomes_file(self):
        assert resolve_target("out.csv") == File("out.csv")

    def test_write_target_passes_through(self):
        target = File("out.json")
        assert resolve_target(target) is target

    def test_non_target_raises(self):
        with pytest.raises(TypeError, match="cannot resolve"):
            resolve_target(42)  # pyright: ignore[reportArgumentType]


class TestResolveFormat:
    @pytest.mark.parametrize(
        ("url", "expected"),
        [("out.csv", "csv"), ("out.jsonl", "jsonl"), ("out", "json")],
    )
    def test_infers_from_extension(self, url, expected):
        assert resolve_format(url, None) == expected

    def test_explicit_format_wins(self):
        assert resolve_format("out.csv", "json") == "json"

    def test_invalid_format_raise(self):
        with pytest.raises(ValueError, match="not a valid Formats"):
            resolve_format("out.txt", None)

        with pytest.raises(ValueError, match="not a valid Formats"):
            resolve_format("out", "txt")


class TestBuildWrite:
    def test_file_forbids_keys(self):
        with pytest.raises(ValueError, match="forbids 'keys'"):
            build_write(File("out.csv"), "append", keys="id")

    def test_file_unsupported_mode(self):
        with pytest.raises(ValueError, match="does not support the 'merge'"):
            build_write(File("out.csv"), "merge")

    def test_file_append_rejected_for_whole_document_format(self):
        """
        A whole-document format cannot be appended to (it would concatenate two
        documents into invalid output), so ``append`` is rejected at prepare.
        """
        with pytest.raises(ValueError, match="does not support the 'append'"):
            build_write(File("out.json"), "append")

        with pytest.raises(ValueError, match="does not support the 'append'"):
            build_write(File("out.geojson"), "append")

    def test_file_append_allowed_for_line_oriented_format(self):
        for dest in ("out.csv", "out.jsonl"):
            spec = build_write(File(dest), "append")
            assert spec.mode is WriteMode.APPEND

    def test_record_store_routes_through_write_operation(self):
        spec = build_write(_RecordStore(), "merge", keys="endpoint_id")

        assert spec.mode is WriteMode.MERGE
        assert spec.keys == ("endpoint_id",)

    def test_record_store_missing_keys_rejected(self):
        with pytest.raises(ValueError, match="requires 'keys'"):
            build_write(_RecordStore(), "merge")


class TestFileDeliver:
    def test_replace_writes_document(self, tmp_path):
        path = tmp_path / "out.json"
        result = File(str(path)).deliver(ITEMS, WriteOperation(WriteMode.REPLACE))

        assert result.written > 0
        assert path.read_bytes() == b'[{"x": 0}, {"x": 1}, {"x": 2}]'

    @async_test
    async def test_adeliver_matches_deliver(self, tmp_path):
        path = tmp_path / "out.json"
        result = await File(str(path)).adeliver(
            ITEMS, WriteOperation(WriteMode.REPLACE)
        )
        assert result.written > 0
        assert path.read_bytes() == b'[{"x": 0}, {"x": 1}, {"x": 2}]'


class TestFileWriter:
    @pytest.mark.parametrize(
        ("dest", "streams"),
        [("out.csv", True), ("out.jsonl", True), ("out.json", False), ("out", False)],
    )
    def test_streamability_negotiated_from_extension(self, dest, streams):
        assert file_writer(dest).stream is streams

    def test_keyed_mode_rejected(self):
        with pytest.raises(ValueError, match="append, replace"):
            file_writer("out.csv", mode="merge")

    def test_append_rejected_for_non_appendable_format(self):
        with pytest.raises(ValueError, match="cannot be appended to"):
            file_writer("out.json", mode="append")

    def test_append_allowed_for_line_oriented_format(self):
        assert file_writer("out.csv", mode="append").mode is WriteMode.APPEND
        assert file_writer("out.jsonl", mode="append").mode is WriteMode.APPEND


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

    def test_streaming_csv_append_across_executions_writes_header_once(self, tmp_path):
        """
        A second append execution against an existing non-empty CSV must not
        re-emit the header. The writer's ``_started`` flag is per-run, so header
        suppression derives from the file already having content.
        """
        path = tmp_path / "out.csv"
        list(SyncPipe(source=[{"x": 0}]).write(str(path), mode="append"))
        list(SyncPipe(source=[{"x": 1}]).write(str(path), mode="append"))
        assert path.read_bytes() == b"x\r\n0\r\n1\r\n"

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

        assert isinstance(result, WriteResult)
        assert result.written > 0
        assert path.read_bytes() == b'[{"x": 0}, {"x": 1}, {"x": 2}]'

    def test_file_rejects_keys(self, tmp_path):
        with pytest.raises(ValueError, match="forbids 'keys'"):
            SyncPipe(source=ITEMS).sink(str(tmp_path / "out.csv"), keys="x")

    @async_test
    async def test_async_sink(self, tmp_path):
        path = tmp_path / "out.json"
        result = await AsyncPipe(source=ITEMS).sink(str(path), mode="replace")
        assert result.written > 0
        assert path.read_bytes() == b'[{"x": 0}, {"x": 1}, {"x": 2}]'


class TestAsyncWriteUnsupported:
    def test_async_pipe_write_raises(self):
        with pytest.raises(NotImplementedError, match="async write"):
            AsyncPipe(source=ITEMS).write("out.json")
