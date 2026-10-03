# vim: sw=4:ts=4:expandtab
"""
Tests target registration, write targets, sessions, and the ``write``/``sink`` verbs.

Covers ``File`` capability resolution, key normalization, ``build_write``
validation, the native whole-stream vs. temporary singleton converter paths, the
csv/jsonl/framed serialization contracts, the session lifecycle state machine, and
passthrough execution (``riko.definitions._targets`` and
``riko.runtime._write_session``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

import pytest

from riko import Pipeline
from riko.bado import as_async
from riko.definitions._targets import (
    FileTarget,
    build_write,
    normalize_strs,
    normalize_target,
    resolve_format,
    validate_target_mode,
)
from riko.definitions._workflow import WriteNode
from riko.definitions._write import WriteCapabilities, WriteMode, WriteResult
from riko.execution._resources import FactoryKind, OneShotResource
from riko.modules.tail import async_pipe as async_tail
from riko.modules.tail import pipe as tail
from riko.runtime import _write_session
from riko.runtime._write_session import (
    _SessionState,
    _SyncFileWriteSession,
    async_file_write_session,
    async_write_through,
    file_write_session,
    mint_write_resource,
    write_through,
)
from riko.types._enums import Backends, Formats
from tests import async_test, skipif_issync

if TYPE_CHECKING:
    from riko.types._io import PathLike
    from riko.types._streams import Feed, Items

ITEMS = [{"x": 0}, {"x": 1}, {"x": 2}]


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


async def _asink(
    items: Feed, dest: PathLike, mode: str = "replace", **kwargs
) -> WriteResult:
    """Delivers the whole stream to *dest* and commits it, as a terminal write does."""
    async with async_file_write_session(build_write(dest, mode, **kwargs)) as session:
        await session.write(items)
        result = await session.afinalize()

    return result


@dataclass(frozen=True)
class _RecordStore:
    """A native keyed target exercising the match-keyed/idempotent branches."""

    backend: ClassVar[Backends] = Backends.AIRTABLE

    def capabilities(self, fmt=None) -> WriteCapabilities:
        return WriteCapabilities(
            modes=frozenset(WriteMode),
            match_keyed_modes=frozenset({WriteMode.MERGE, WriteMode.DELETE}),
            idempotent_modes=frozenset({WriteMode.APPEND}),
        )


class TestResolveTarget:
    def test_write_target_passes_through(self):
        target = FileTarget("out.json")
        assert normalize_target(target) is target

    def test_non_target_raises(self):
        with pytest.raises(TypeError, match="cannot resolve"):
            normalize_target(42)  # pyright: ignore[reportArgumentType]


class TestResolveFormat:
    def test_explicit_format_wins(self):
        assert resolve_format("out.csv", "json") == "json"

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError, match="Invalid Formats"):
            resolve_format("out.txt", None)


class TestNormalizeKeys:
    def test_empty_key_rejected(self):
        with pytest.raises(ValueError, match="non-empty"):
            normalize_strs(["id", ""])

    def test_duplicate_keys_rejected(self):
        with pytest.raises(ValueError, match="duplicate"):
            normalize_strs(["id", "id"])

    @pytest.mark.parametrize("value", [[1, 2], ["a", 1], [None]])
    def test_non_string_keys_rejected(self, value):
        with pytest.raises(ValueError, match="non-empty strings"):
            normalize_strs(value)

    def test_non_iterable_rejected(self):
        with pytest.raises(TypeError, match="string or iterable"):
            normalize_strs(42)  # pyright: ignore[reportArgumentType]


class TestFileCapabilities:
    @pytest.mark.parametrize(
        ("dest", "appendable", "incremental"),
        [
            ("out.csv", True, True),
            ("out.jsonl", True, True),
            ("out.json", False, False),
            ("out.geojson", False, False),
        ],
    )
    def test_target_owns_format_behavior(self, dest, appendable, incremental):
        capabilities = FileTarget(dest).capabilities()

        assert capabilities.serializes is True
        assert capabilities.appendable is appendable
        assert (WriteMode.APPEND in capabilities.modes) is appendable
        assert capabilities.incremental is incremental
        assert WriteMode.REPLACE in capabilities.modes


class TestValidateTargetMode:
    def test_match_keyed_without_keys_rejected(self):
        capabilities = _RecordStore().capabilities()
        with pytest.raises(ValueError, match="requires 'keys'"):
            validate_target_mode(_RecordStore(), WriteMode.MERGE, capabilities)

    @pytest.mark.parametrize(
        ("mode", "keys"),
        [
            pytest.param(WriteMode.MERGE, ("id",), id="match-keyed"),
            pytest.param(WriteMode.APPEND, (), id="idempotent-unkeyed"),
            pytest.param(WriteMode.APPEND, ("id",), id="idempotent-keyed"),
        ],
    )
    def test_supported_key_combinations(self, mode, keys):
        capabilities = _RecordStore().capabilities()
        validate_target_mode(_RecordStore(), mode, capabilities, keys=keys)

    def test_unkeyed_mode_with_keys_rejected(self):
        capabilities = FileTarget("out.csv").capabilities()
        target = FileTarget("out.csv")

        with pytest.raises(ValueError, match="forbids 'keys'"):
            validate_target_mode(target, WriteMode.APPEND, capabilities, keys=("x",))


class TestPrepareWrite:
    def test_path_defaults_to_extension_format_and_replace(self):
        prepared = build_write("out.csv")
        assert prepared.fmt is Formats.CSV
        assert prepared.operation.mode is WriteMode.REPLACE

    def test_file_unsupported_mode(self):
        with pytest.raises(ValueError, match="does not support the 'merge'"):
            build_write(FileTarget("out.csv"), "merge")

    @pytest.mark.parametrize("dest", ["out.json", "out.geojson"])
    def test_file_append_rejected_for_framed_format(self, dest):
        with pytest.raises(ValueError, match="does not support the 'append'"):
            build_write(FileTarget(dest), "append")

    def test_record_store_binds_match_keys(self):
        prepared = build_write(_RecordStore(), "merge", keys="endpoint_id")

        assert prepared.operation.mode is WriteMode.MERGE
        assert prepared.operation.keys == ("endpoint_id",)


class TestConverterPath:
    """The native whole-stream path and the temporary singleton path."""

    def _spy(self, monkeypatch):
        calls = []
        original = _write_session.serialize_records

        def spy(items, fmt, **kwargs):
            materialized = list(items)
            calls.append(materialized)
            return original(materialized, fmt, **kwargs)

        monkeypatch.setattr(_write_session, "serialize_records", spy)
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


class TestCsv:
    def test_replace_writes_header_once(self, tmp_path):
        path = tmp_path / "out.csv"
        _sink(ITEMS, path)
        assert path.read_bytes() == b"x\r\n0\r\n1\r\n2\r\n"

    def test_append_existing_skips_header(self, tmp_path):
        path = tmp_path / "out.csv"
        _sink([{"x": 0}], path)
        _sink([{"x": 1}], path, "append")
        assert path.read_bytes() == b"x\r\n0\r\n1\r\n"

    def test_append_empty_emits_header(self, tmp_path):
        path = tmp_path / "out.csv"
        _sink([{"x": 0}], path, "append")
        assert path.read_bytes() == b"x\r\n0\r\n"

    def test_append_existing_without_newline_inserts_boundary(self, tmp_path):
        path = tmp_path / "out.csv"
        path.write_bytes(b"x\r\n0")
        _sink([{"x": 1}], path, "append")
        assert path.read_bytes() == b"x\r\n0\n1\r\n"

    def test_empty_append_does_not_mutate(self, tmp_path):
        path = tmp_path / "out.csv"
        path.write_bytes(b"x\r\n0\r\n")
        _sink([], path, "append")
        assert path.read_bytes() == b"x\r\n0\r\n"

    def test_passthrough_singleton_preserves_schema(self, tmp_path):
        path = tmp_path / "out.csv"
        rows = [{"a": 1, "b": 2}, {"b": 4, "a": 3}]
        list(write_through(rows, build_write(path), terminating=_never))
        assert path.read_bytes() == b"a,b\r\n1,2\r\n3,4\r\n"

    def test_passthrough_unexpected_field_raises(self, tmp_path):
        path = tmp_path / "out.csv"
        rows = [{"a": 1}, {"a": 2, "b": 3}]

        with pytest.raises(ValueError, match="unexpected fields"):
            list(write_through(rows, build_write(path), terminating=_never))


class TestJsonl:
    def test_native_stream_has_no_array(self, tmp_path):
        path = tmp_path / "out.jsonl"
        _sink(ITEMS, path)
        assert path.read_bytes() == b'{"x": 0}\n{"x": 1}\n{"x": 2}\n'

    def test_singleton_has_no_array(self, tmp_path):
        path = tmp_path / "out.jsonl"
        list(write_through(ITEMS, build_write(path), terminating=_never))
        assert path.read_bytes() == b'{"x": 0}\n{"x": 1}\n{"x": 2}\n'

    def test_append_newline_terminated_concatenates(self, tmp_path):
        path = tmp_path / "out.jsonl"
        path.write_bytes(b'{"x": 0}\n')
        _sink([{"x": 1}], path, "append")
        assert path.read_bytes() == b'{"x": 0}\n{"x": 1}\n'

    def test_append_unterminated_inserts_one_boundary(self, tmp_path):
        path = tmp_path / "out.jsonl"
        path.write_bytes(b'{"x": 0}')
        _sink([{"x": 1}], path, "append")
        assert path.read_bytes() == b'{"x": 0}\n{"x": 1}\n'

    def test_empty_append_does_not_mutate(self, tmp_path):
        path = tmp_path / "out.jsonl"
        path.write_bytes(b'{"x": 0}\n')
        _sink([], path, "append")
        assert path.read_bytes() == b'{"x": 0}\n'


class TestFramed:
    def test_passthrough_buffers_until_finalize(self, tmp_path):
        path = tmp_path / "out.json"
        stream = write_through(ITEMS, build_write(path), terminating=_never)
        next(stream)
        assert not path.exists()
        list(stream)
        assert path.read_bytes() == b'[{"x": 0}, {"x": 1}, {"x": 2}]'

    def test_sink_writes_one_document(self, tmp_path):
        path = tmp_path / "out.json"
        result = _sink(ITEMS, path)
        assert result.written > 0
        assert path.read_bytes() == b'[{"x": 0}, {"x": 1}, {"x": 2}]'

    def test_abort_discards_staged_document(self, tmp_path):
        path = tmp_path / "out.json"
        prepared = build_write(path)

        with file_write_session(prepared) as session:
            session.write(ITEMS)
            session.abort()

        assert not path.exists()


class TestMintWriteResource:
    def test_never_stored_in_context(self):
        resource = mint_write_resource("report.csv")

        assert isinstance(resource, OneShotResource)
        assert resource.reusable is False
        assert resource.external is False
        assert resource.kind is FactoryKind.SYNC_CONTEXTMANAGER


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
        session.teardown()

    def test_open_to_aborted(self, tmp_path):
        session = self._session(tmp_path)
        session.abort()
        assert session._state is _SessionState.ABORTED
        session.teardown()

    def test_write_after_finalize_rejected(self, tmp_path):
        session = self._session(tmp_path)
        session.write(ITEMS)
        session.finalize()

        with pytest.raises(RuntimeError, match="finalized"):
            session.write(ITEMS)

        session.teardown()

    def test_write_after_abort_rejected(self, tmp_path):
        session = self._session(tmp_path)
        session.abort()

        with pytest.raises(RuntimeError, match="aborted"):
            session.write(ITEMS)

        session.teardown()

    def test_finalize_twice_returns_cached(self, tmp_path):
        session = self._session(tmp_path)
        session.write(ITEMS)
        assert session.finalize() is session.finalize()
        session.teardown()

    def test_teardown_twice_is_safe(self, tmp_path):
        session = self._session(tmp_path)
        session.teardown()
        session.teardown()

    def test_teardown_never_commits(self, tmp_path):
        path = tmp_path / "out.json"
        session = _SyncFileWriteSession(build_write(path))
        session.acquire()
        session.write(ITEMS)
        session.teardown()
        assert not path.exists()

    def test_incremental_abort_keeps_written_bytes(self, tmp_path):
        path = tmp_path / "out.jsonl"
        session = _SyncFileWriteSession(build_write(path))
        session.acquire()
        session.write({"x": 1})
        session.abort()
        session.teardown()
        assert path.read_bytes() == b'{"x": 1}\n'

    def test_stream_then_item_rejected(self, tmp_path):
        session = self._session(tmp_path)
        session.write(ITEMS)

        with pytest.raises(RuntimeError, match="cannot mix item and stream"):
            session.write({"x": 0})

        session.teardown()

    def test_item_then_stream_rejected(self, tmp_path):
        session = self._session(tmp_path)
        session.write({"x": 0})

        with pytest.raises(RuntimeError, match="cannot mix item and stream"):
            session.write(ITEMS)

        session.teardown()

    def test_two_whole_streams_rejected(self, tmp_path):
        session = self._session(tmp_path)
        session.write(ITEMS)

        with pytest.raises(RuntimeError, match="cannot attempt multiple stream"):
            session.write(ITEMS)

        session.teardown()


class TestSyncWriteExecution:
    def test_passthrough_preserves_stream(self, tmp_path):
        prepared = build_write(tmp_path / "out.json")
        assert list(write_through(ITEMS, prepared, terminating=_never)) == ITEMS

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


@skipif_issync
class TestAsyncWriteExecution:
    @async_test
    async def test_passthrough_preserves_stream(self, tmp_path):
        prepared = build_write(tmp_path / "out.json")
        stream = async_write_through(as_async(ITEMS), prepared, terminating=_never)
        assert [item async for item in stream] == ITEMS

    @async_test
    async def test_writes_mid_chain(self, tmp_path):
        path = tmp_path / "out.json"
        stream = async_write_through(
            as_async(ITEMS), build_write(path), terminating=_never
        )
        tailed = async_tail(stream, conf={"count": 1})
        assert [item async for item in tailed] == [{"x": 2}]
        assert path.read_bytes() == b'[{"x": 0}, {"x": 1}, {"x": 2}]'

    @async_test
    async def test_csv_singleton_preserves_schema(self, tmp_path):
        path = tmp_path / "out.csv"
        rows = [{"a": 1, "b": 2}, {"b": 4, "a": 3}]
        stream = async_write_through(
            as_async(rows), build_write(path), terminating=_never
        )
        _ = [item async for item in stream]
        assert path.read_bytes() == b"a,b\r\n1,2\r\n3,4\r\n"

    @async_test
    async def test_graceful_close_finalizes_prefix(self, tmp_path):
        path = tmp_path / "out.json"
        stream = async_write_through(
            as_async(ITEMS), build_write(path), terminating=_never
        )
        await anext(stream)
        await stream.aclose()
        assert path.read_bytes() == b'[{"x": 0}]'

    @async_test
    async def test_terminate_aborts(self, tmp_path):
        path = tmp_path / "out.json"
        stream = async_write_through(
            as_async(ITEMS), build_write(path), terminating=_always
        )
        await anext(stream)
        await stream.aclose()
        assert not path.exists()

    @async_test
    async def test_exception_aborts(self, tmp_path):
        path = tmp_path / "out.json"
        stream = async_write_through(
            as_async(ITEMS), build_write(path), terminating=_never
        )
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
    def test_terminal_returns_result(self, tmp_path):
        result = _sink(ITEMS, tmp_path / "out.json")

        assert isinstance(result, WriteResult)
        assert result.written > 0

    def test_file_rejects_keys(self, tmp_path):
        with pytest.raises(ValueError, match="forbids 'keys'"):
            build_write(tmp_path / "out.csv", keys="x")

    def test_non_file_target_execution_unsupported(self):
        prepared = build_write(_RecordStore(), "replace")

        with (
            pytest.raises(NotImplementedError, match="only file targets"),
            file_write_session(prepared),
        ):
            pass  # pragma: no cover


WRITE_NODE_PENDING = pytest.mark.xfail(
    strict=True, reason="write nodes do not execute yet"
)


class TestPipelineWriteDefinition:
    """The ``write`` verb validates its destination when the node is declared."""

    def test_file_rejects_keys(self, tmp_path):
        with pytest.raises(ValueError, match="forbids 'keys'"):
            Pipeline(source=ITEMS).write(tmp_path / "out.csv", keys="x")

    def test_declares_the_resolved_format_and_mode(self, tmp_path):
        pipeline = Pipeline(source=ITEMS).write(tmp_path / "out.csv", mode="append")
        node = pipeline.workflow.nodes["write-1"]
        assert isinstance(node, WriteNode)
        assert (node.fmt, node.mode, node.keys) == (Formats.CSV, WriteMode.APPEND, ())


@WRITE_NODE_PENDING
class TestPipelineWrite:
    """The ``write`` verb at the pipeline level, once a write node can run."""

    def test_passthrough_preserves_stream(self, tmp_path):
        pipeline = Pipeline(source=ITEMS).write(tmp_path / "out.json")
        assert list(pipeline) == ITEMS

    def test_writes_mid_chain(self, tmp_path):
        path = tmp_path / "out.json"
        pipeline = Pipeline(source=ITEMS).write(path).tail(conf={"count": 1})
        assert list(pipeline) == [{"x": 2}]
        assert path.read_bytes() == b'[{"x": 0}, {"x": 1}, {"x": 2}]'

    def test_replace_defers_truncation_until_consumed(self, tmp_path):
        path = tmp_path / "out.jsonl"
        path.write_bytes(b'{"old": 1}\n')
        pipeline = Pipeline(source=ITEMS).write(path, mode="replace")
        assert path.read_bytes() == b'{"old": 1}\n'
        list(pipeline)
        assert path.read_bytes() == b'{"x": 0}\n{"x": 1}\n{"x": 2}\n'

    def test_graceful_close_finalizes_prefix(self, tmp_path):
        path = tmp_path / "out.json"
        stream = iter(Pipeline(source=ITEMS).write(path))
        next(stream)
        stream.close()
        assert path.read_bytes() == b'[{"x": 0}]'

    def test_exception_aborts(self, tmp_path):
        path = tmp_path / "out.json"
        stream = iter(Pipeline(source=ITEMS).write(path))
        next(stream)

        with pytest.raises(RuntimeError, match="boom"):
            stream.throw(RuntimeError("boom"))

        assert not path.exists()

    def test_csv_writes_the_header_once(self, tmp_path):
        path = tmp_path / "out.csv"
        list(Pipeline(source=ITEMS).write(path))
        assert path.read_bytes() == b"x\r\n0\r\n1\r\n2\r\n"

    def test_jsonl_has_no_array(self, tmp_path):
        path = tmp_path / "out.jsonl"
        list(Pipeline(source=ITEMS).write(path))
        assert path.read_bytes() == b'{"x": 0}\n{"x": 1}\n{"x": 2}\n'

    def test_leaf_write_produces_one_framed_document(self, tmp_path):
        path = tmp_path / "out.json"
        pipeline = Pipeline(source=ITEMS).hash(options={"assign": "h"}).write(path)
        assert len(list(pipeline)) == len(ITEMS)
        assert path.read_bytes().startswith(b"[")
        assert path.read_bytes().endswith(b"]")

    def test_non_file_target_execution_unsupported(self):
        pipeline = Pipeline(source=ITEMS).write(_RecordStore())

        with pytest.raises(NotImplementedError, match="only file targets"):
            list(pipeline)

    def test_write_does_not_rerun_preceding_module(self, tmp_path):
        once = list(Pipeline(source=ITEMS).hash(options={"assign": "h"}))
        source = Pipeline(source=ITEMS).hash(options={"assign": "h"})
        through = list(source.write(tmp_path / "out.json"))
        assert through == once
