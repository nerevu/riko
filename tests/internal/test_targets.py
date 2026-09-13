# vim: sw=4:ts=4:expandtab
"""
Tests the write targets, sessions, and the ``write``/``sink`` verbs.

Covers ``File`` capability resolution, key normalization, ``prepare_write``
validation, the native whole-stream vs. temporary singleton converter paths, the
csv/jsonl/framed serialization contracts, the session lifecycle state machine, and
the passthrough execution host (``riko.targets``/``riko._write_session``).
"""

from dataclasses import dataclass

import pytest

from riko import _write_session, get_path
from riko._write_session import (
    _SessionState,
    _SyncFileWriteSession,
    file_write_session,
    mint_write_resource,
)
from riko.collections import AsyncPipe, SyncCollection, SyncPipe
from riko.resources import OneShotResource, _FactoryKind
from riko.targets import (
    File,
    WriteCapabilities,
    WriteResult,
    normalize_keys,
    prepare_write,
    resolve_format,
    resolve_target,
    validate_target_mode,
)
from riko.types._write import WriteMode
from tests import skipif_issync

ITEMS = [{"x": 0}, {"x": 1}, {"x": 2}]


@dataclass(frozen=True)
class _RecordStore:
    """A native keyed target exercising the match-keyed/idempotent branches."""

    def capabilities(self, fmt=None) -> WriteCapabilities:
        return WriteCapabilities(
            modes=frozenset(WriteMode),
            match_keyed_modes=frozenset({WriteMode.MERGE, WriteMode.DELETE}),
            idempotent_modes=frozenset({WriteMode.APPEND}),
        )


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

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError, match="not a valid Formats"):
            resolve_format("out.txt", None)


class TestNormalizeKeys:
    def test_wraps_bare_string(self):
        assert normalize_keys("id") == ("id",)

    def test_preserves_iterable_order(self):
        assert normalize_keys(["b", "a"]) == ("b", "a")

    def test_none_is_empty(self):
        assert normalize_keys(None) == ()

    def test_empty_key_rejected(self):
        with pytest.raises(ValueError, match="non-empty"):
            normalize_keys(["id", ""])

    def test_duplicate_keys_rejected(self):
        with pytest.raises(ValueError, match="duplicate"):
            normalize_keys(["id", "id"])


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
        capabilities = File(dest).capabilities()

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

    def test_match_keyed_with_keys_accepted(self):
        capabilities = _RecordStore().capabilities()
        keys = ("id",)
        validate_target_mode(_RecordStore(), WriteMode.MERGE, capabilities, keys=keys)

    def test_idempotent_without_keys_accepted(self):
        capabilities = _RecordStore().capabilities()
        validate_target_mode(_RecordStore(), WriteMode.APPEND, capabilities)

    def test_idempotent_with_keys_accepted(self):
        capabilities = _RecordStore().capabilities()
        keys = ("id",)
        validate_target_mode(_RecordStore(), WriteMode.APPEND, capabilities, keys=keys)

    def test_unkeyed_mode_with_keys_rejected(self):
        capabilities = File("out.csv").capabilities()
        target = File("out.csv")

        with pytest.raises(ValueError, match="forbids 'keys'"):
            validate_target_mode(target, WriteMode.APPEND, capabilities, keys=("x",))


class TestPrepareWrite:
    def test_file_forbids_keys(self):
        with pytest.raises(ValueError, match="forbids 'keys'"):
            prepare_write(File("out.csv"), "append", keys="id")

    def test_file_unsupported_mode(self):
        with pytest.raises(ValueError, match="does not support the 'merge'"):
            prepare_write(File("out.csv"), "merge")

    def test_file_append_rejected_for_framed_format(self):
        for dest in ("out.json", "out.geojson"):
            with pytest.raises(ValueError, match="does not support the 'append'"):
                prepare_write(File(dest), "append")

    def test_file_append_allowed_for_line_oriented_format(self):
        for dest in ("out.csv", "out.jsonl"):
            prepared = prepare_write(File(dest), "append")
            assert prepared.operation.mode is WriteMode.APPEND

    def test_record_store_binds_match_keys(self):
        prepared = prepare_write(_RecordStore(), "merge", keys="endpoint_id")

        assert prepared.operation.mode is WriteMode.MERGE
        assert prepared.operation.keys == ("endpoint_id",)

    def test_record_store_missing_keys_rejected(self):
        with pytest.raises(ValueError, match="requires 'keys'"):
            prepare_write(_RecordStore(), "merge")


class TestConverterPath:
    """The native whole-stream path and the temporary singleton path (§34)."""

    def _spy(self, monkeypatch):
        calls = []
        original = _write_session.convert_records

        def spy(items, fmt, **kwargs):
            materialized = list(items)
            calls.append(materialized)
            return original(materialized, fmt, **kwargs)

        monkeypatch.setattr(_write_session, "convert_records", spy)
        return calls

    def test_sink_converts_whole_stream_once(self, monkeypatch, tmp_path):
        calls = self._spy(monkeypatch)
        SyncPipe(source=ITEMS).sink(tmp_path / "out.jsonl", mode="replace")

        assert len(calls) == 1
        assert calls[0] == ITEMS

    def test_passthrough_converts_per_item(self, monkeypatch, tmp_path):
        calls = self._spy(monkeypatch)
        flow = SyncPipe(source=ITEMS).write(tmp_path / "out.jsonl")
        yielded = list(flow)

        assert yielded == ITEMS
        assert len(calls) == len(ITEMS)


class TestCsv:
    def test_replace_writes_header_once(self, tmp_path):
        path = tmp_path / "out.csv"
        SyncPipe(source=ITEMS).sink(path, mode="replace")
        assert path.read_bytes() == b"x\r\n0\r\n1\r\n2\r\n"

    def test_append_existing_skips_header(self, tmp_path):
        path = tmp_path / "out.csv"
        SyncPipe(source=[{"x": 0}]).sink(path, mode="replace")
        SyncPipe(source=[{"x": 1}]).sink(path, mode="append")
        assert path.read_bytes() == b"x\r\n0\r\n1\r\n"

    def test_append_empty_emits_header(self, tmp_path):
        path = tmp_path / "out.csv"
        SyncPipe(source=[{"x": 0}]).sink(path, mode="append")
        assert path.read_bytes() == b"x\r\n0\r\n"

    def test_append_existing_without_newline_inserts_boundary(self, tmp_path):
        path = tmp_path / "out.csv"
        path.write_bytes(b"x\r\n0")
        SyncPipe(source=[{"x": 1}]).sink(path, mode="append")
        assert path.read_bytes() == b"x\r\n0\n1\r\n"

    def test_empty_append_does_not_mutate(self, tmp_path):
        path = tmp_path / "out.csv"
        path.write_bytes(b"x\r\n0\r\n")
        SyncPipe(source=[]).sink(path, mode="append")
        assert path.read_bytes() == b"x\r\n0\r\n"

    def test_passthrough_singleton_preserves_schema(self, tmp_path):
        path = tmp_path / "out.csv"
        rows = [{"a": 1, "b": 2}, {"b": 4, "a": 3}]
        list(SyncPipe(source=rows).write(path))
        assert path.read_bytes() == b"a,b\r\n1,2\r\n3,4\r\n"

    def test_passthrough_unexpected_field_raises(self, tmp_path):
        path = tmp_path / "out.csv"
        rows = [{"a": 1}, {"a": 2, "b": 3}]
        with pytest.raises(ValueError, match="unexpected fields"):
            list(SyncPipe(source=rows).write(path))


class TestJsonl:
    def test_native_stream_has_no_array(self, tmp_path):
        path = tmp_path / "out.jsonl"
        SyncPipe(source=ITEMS).sink(path, mode="replace")
        assert path.read_bytes() == b'{"x": 0}\n{"x": 1}\n{"x": 2}\n'

    def test_singleton_has_no_array(self, tmp_path):
        path = tmp_path / "out.jsonl"
        list(SyncPipe(source=ITEMS).write(path))
        assert path.read_bytes() == b'{"x": 0}\n{"x": 1}\n{"x": 2}\n'

    def test_ends_in_single_newline(self, tmp_path):
        path = tmp_path / "out.jsonl"
        SyncPipe(source=ITEMS).sink(path, mode="replace")
        data = path.read_bytes()
        assert data.endswith(b"\n")
        assert not data.endswith(b"\n\n")

    def test_append_newline_terminated_concatenates(self, tmp_path):
        path = tmp_path / "out.jsonl"
        path.write_bytes(b'{"x": 0}\n')
        SyncPipe(source=[{"x": 1}]).sink(path, mode="append")
        assert path.read_bytes() == b'{"x": 0}\n{"x": 1}\n'

    def test_append_unterminated_inserts_one_boundary(self, tmp_path):
        path = tmp_path / "out.jsonl"
        path.write_bytes(b'{"x": 0}')
        SyncPipe(source=[{"x": 1}]).sink(path, mode="append")
        assert path.read_bytes() == b'{"x": 0}\n{"x": 1}\n'

    def test_empty_append_does_not_mutate(self, tmp_path):
        path = tmp_path / "out.jsonl"
        path.write_bytes(b'{"x": 0}\n')
        SyncPipe(source=[]).sink(path, mode="append")
        assert path.read_bytes() == b'{"x": 0}\n'


class TestFramed:
    def test_passthrough_buffers_until_finalize(self, tmp_path):
        path = tmp_path / "out.json"
        flow = SyncPipe(source=ITEMS).write(path)
        next(flow)
        assert not path.exists()
        list(flow)
        assert path.read_bytes() == b'[{"x": 0}, {"x": 1}, {"x": 2}]'

    def test_sink_writes_one_document(self, tmp_path):
        path = tmp_path / "out.json"
        flow = SyncPipe(source=ITEMS).sink(path, mode="replace")
        assert flow.written > 0
        assert path.read_bytes() == b'[{"x": 0}, {"x": 1}, {"x": 2}]'

    def test_abort_discards_staged_document(self, tmp_path):
        path = tmp_path / "out.json"
        prepared = prepare_write(path)

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
        assert resource.kind is _FactoryKind.SYNC_CONTEXTMANAGER


class TestSessionLifecycle:
    def _session(self, tmp_path, name="out.json"):
        session = _SyncFileWriteSession(prepare_write(tmp_path / name))
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
        session = _SyncFileWriteSession(prepare_write(path))
        session.acquire()
        session.write(ITEMS)
        session.teardown()
        assert not path.exists()

    def test_incremental_abort_keeps_written_bytes(self, tmp_path):
        path = tmp_path / "out.jsonl"
        session = _SyncFileWriteSession(prepare_write(path))
        session.acquire()
        session.write({"x": 1})
        session.abort()
        session.teardown()
        assert path.read_bytes() == b'{"x": 1}\n'


class TestSyncWriteExecution:
    def test_passthrough_preserves_stream(self, tmp_path):
        flow = SyncPipe(source=ITEMS).write(tmp_path / "out.json")
        assert list(flow) == ITEMS

    def test_writes_mid_chain(self, tmp_path):
        path = tmp_path / "out.json"
        flow = SyncPipe(source=ITEMS).write(path).tail(conf={"count": 1})
        assert list(flow) == [{"x": 2}]
        assert path.read_bytes() == b'[{"x": 0}, {"x": 1}, {"x": 2}]'

    def test_graceful_close_finalizes_prefix(self, tmp_path):
        path = tmp_path / "out.json"
        flow = SyncPipe(source=ITEMS).write(path)
        next(flow)
        flow.close()
        assert path.read_bytes() == b'[{"x": 0}]'

    def test_terminate_aborts(self, tmp_path):
        path = tmp_path / "out.json"
        flow = SyncPipe(source=ITEMS).write(path)
        next(flow)
        flow.terminate()
        assert flow._terminating
        assert not path.exists()

    def test_exceptional_context_exit_aborts(self, tmp_path):
        path = tmp_path / "out.json"

        def boom():
            with SyncPipe(source=ITEMS).write(path) as flow:
                next(flow)
                raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            boom()

        assert not path.exists()


@skipif_issync
class TestAsyncWriteExecution:
    @pytest.mark.anyio
    async def test_passthrough_preserves_stream(self, tmp_path):
        flow = AsyncPipe(source=ITEMS).write(tmp_path / "out.json")
        assert [item async for item in flow] == ITEMS

    @pytest.mark.anyio
    async def test_writes_mid_chain(self, tmp_path):
        path = tmp_path / "out.json"
        flow = AsyncPipe(source=ITEMS).write(path).tail(conf={"count": 1})
        assert [item async for item in flow] == [{"x": 2}]
        assert path.read_bytes() == b'[{"x": 0}, {"x": 1}, {"x": 2}]'

    @pytest.mark.xfail(
        reason="async pipe terminate is not yet implemented.", strict=True
    )
    @pytest.mark.anyio
    async def test_graceful_close_finalizes_prefix(self, tmp_path):
        path = tmp_path / "out.json"
        flow = AsyncPipe(source=ITEMS).write(path)
        await anext(flow)
        await flow.aclose()
        assert path.read_bytes() == b'[{"x": 0}]'

    @pytest.mark.xfail(
        reason="async pipe terminate is not yet implemented.", strict=True
    )
    @pytest.mark.anyio
    async def test_terminate_aborts(self, tmp_path):
        path = tmp_path / "out.json"
        flow = AsyncPipe(source=ITEMS).write(path)
        await anext(flow)
        await flow.terminate()
        assert flow._terminating
        assert not path.exists()

    @pytest.mark.xfail(
        reason="async pipe context manager is not yet implemented.", strict=True
    )
    @pytest.mark.anyio
    async def test_exceptional_context_exit_aborts(self, tmp_path):
        path = tmp_path / "out.json"

        async def boom():
            async with AsyncPipe(source=ITEMS).write(path) as flow:
                await anext(flow)
                raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            await boom()

        assert not path.exists()


class TestPassthroughHost:
    def test_write_does_not_rerun_preceding_module(self, tmp_path):
        once = list(SyncPipe(source=ITEMS).hash())
        through = list(SyncPipe(source=ITEMS).hash().write(tmp_path / "out.json"))
        assert through == once

    def test_write_returns_identity_pipe(self, tmp_path):
        flow = SyncPipe(source=ITEMS).write(tmp_path / "out.json")
        assert isinstance(flow, SyncPipe)
        assert flow.name == ""

    def test_collection_write_has_no_name_attribute_error(self, tmp_path):
        path = tmp_path / "out.csv"
        sources = [{"url": get_path("feed.xml")}]
        flow = SyncCollection(sources).write(path)
        assert isinstance(flow, SyncPipe)
        assert flow.name == ""
        assert list(flow)
        assert path.exists()


class TestSink:
    def test_terminal_returns_result(self, tmp_path):
        path = tmp_path / "out.json"
        flow = SyncPipe(source=ITEMS).sink(path, mode="replace")

        assert isinstance(flow, WriteResult)
        assert flow.written > 0

    def test_file_rejects_keys(self, tmp_path):
        with pytest.raises(ValueError, match="forbids 'keys'"):
            SyncPipe(source=ITEMS).sink(tmp_path / "out.csv", keys="x")
