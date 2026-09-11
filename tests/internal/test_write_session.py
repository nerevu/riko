# vim: sw=4:ts=4:expandtab
"""
TDD red-phase spec for the write-session layer that ``write``/``sink`` sit on.

These tests describe the intended behavior of the execution-owned write session that
``write()`` mints internally — the acquire, write item, finalize, teardown lifecycle
that replaces the hidden ``send``/``on_receive`` writer. That session machinery in
``riko.targets`` is currently only a sketch (stub bodies raise ``NotImplementedError``),
so every test here is expected to FAIL until the lifecycle is implemented. They pin the
contract the implementation must satisfy:

- ``mint_write_resource`` produces an anonymous, execution-local one-shot resource;
- ``file_write_session`` is a one-acquisition lifecycle that validates at prepare and
  finalizes on teardown;
- ``_FileWriteSession`` negotiates incremental vs. buffered delivery and derives csv
  header suppression from the file's existing content (the double-header fix);
- ``write`` and ``sink`` converge on the same ``WriteOperation`` specification.
"""

import pytest

from riko._write_session import (
    _FileWriteSession,
    file_write_session,
    mint_write_resource,
)
from riko.context import Context
from riko.resources import OneShotResource, _FactoryKind, classify_factory
from riko.targets import Formats, WriteResult, prepare_write
from riko.types._write import WriteMode
from tests import async_test

ITEMS = [{"x": 0}, {"x": 1}, {"x": 2}]


def _session(dest, fmt, *, mode=WriteMode.REPLACE) -> _FileWriteSession:
    """Builds a file write session bound to ``dest`` for the given format."""
    prepared = prepare_write(dest, mode=mode, fmt=fmt)
    return _FileWriteSession(prepared)


class TestMintWriteResource:
    def test_mints_execution_local_one_shot(self):
        """The path string mints an anonymous one-shot session resource."""
        resource = mint_write_resource("report.csv")

        assert isinstance(resource, OneShotResource)
        assert resource.reusable is False
        assert resource.external is False

    def test_wraps_a_lifecycle_factory(self):
        """The minted resource wraps the ``file_write_session`` context manager lifecycle."""
        resource = mint_write_resource("report.jsonl")
        assert resource.kind is _FactoryKind.SYNC_CONTEXTMANAGER

    def test_never_stored_in_context(self):
        """A one-shot session resource is un-reusable, so Context rejects it."""
        resource = mint_write_resource("report.csv")

        with pytest.raises(TypeError):
            Context().with_resource("out", resource)  # pyright: ignore[reportArgumentType]


class TestWriteSessionLifecycle:
    def test_classifies_as_sync_gen_lifecycle(self):
        """``file_write_session`` is a context manager lifecycle ``from_lifecycle`` can wrap."""
        prepared = prepare_write("out.jsonl")
        factory = file_write_session(prepared)
        assert classify_factory(factory) is _FactoryKind.SYNC_CONTEXTMANAGER

    def test_yields_live_session(self, tmp_path):
        """The lifecycle acquires and yields the live session, once."""
        prepared = prepare_write(tmp_path / "out.jsonl")

        with file_write_session(prepared) as session:
            assert isinstance(session, _FileWriteSession)

    def test_teardown_finalizes(self, tmp_path):
        """Closing the lifecycle finalizes: the buffered document is flushed."""
        path = tmp_path / "out.json"
        prepared = prepare_write(path)

        with file_write_session(prepared) as session:
            for item in ITEMS:
                session.write(item)

        assert path.read_bytes() == b'[{"x": 0}, {"x": 1}, {"x": 2}]'

    def test_append_to_whole_document_rejected_at_prepare(self, tmp_path):
        """Appending to a whole-document format is rejected before acquisition."""
        with pytest.raises(ValueError, match="File does not support 'append'"):
            prepare_write(tmp_path / "out.json", mode="append")


class TestFileWriteSession:
    def test_jsonl_written_incrementally(self, tmp_path):
        """A streamable format writes each record as it arrives, matching the old writer."""
        path = tmp_path / "out.jsonl"
        session = _session(path, Formats.JSONL, mode=WriteMode.APPEND)
        session.write({"x": 0})
        assert path.read_bytes() == b'{"x": 0}'

        session.write({"x": 1})
        session.finalize()
        assert path.read_bytes() == b'{"x": 0}\n{"x": 1}\n'

    def test_json_buffered_until_finalize(self, tmp_path):
        """A whole-document format buffers, writing one document at finalize."""
        path = tmp_path / "out.json"
        session = _session(path, Formats.JSON)

        session.write({"x": 0})
        session.write({"x": 1})
        assert not path.exists()

        session.finalize()
        assert path.read_bytes() == b'[{"x": 0}, {"x": 1}]'

    def test_finalize_reports_written(self, tmp_path):
        """Finalize returns a ``WriteResult`` carrying the bytes written."""
        session = _session(tmp_path / "out.jsonl", Formats.JSONL, mode=WriteMode.APPEND)
        session.write({"x": 0})
        result = session.finalize()

        assert isinstance(result, WriteResult)
        assert result.written > 0

    def test_csv_append_across_sessions_writes_header_once(self, tmp_path):
        """
        A second append session against an existing non-empty csv must not re-emit the
        header. Suppression derives from the file already having content, not an in-run
        flag (the double-header fix).
        """
        path = tmp_path / "out.csv"

        first = _session(path, Formats.CSV, mode=WriteMode.APPEND)
        first.write({"x": 0})
        first.write({"x": 1})
        first.finalize()

        second = _session(path, Formats.CSV, mode=WriteMode.APPEND)
        second.write({"x": 2})
        second.write({"x": 3})
        second.finalize()

        assert path.read_bytes() == b"x\r\n0\r\n1\r\n2\r\n3\r\n"

    @async_test
    async def test_awrite_incremental(self, tmp_path):
        """The async session delivers records through ``awrite``."""
        path = tmp_path / "out.jsonl"
        session = _session(path, Formats.JSONL, mode=WriteMode.APPEND)

        await session.awrite({"x": 0})
        session.finalize()
        assert path.read_bytes() == b'{"x": 0}\n'


class TestWriteSinkConvergence:
    def test_session_carries_the_specification_operation(self, tmp_path):
        """
        The session the lifecycle yields carries the same ``WriteOperation`` the
        specification layer builds — ``write`` and ``sink`` converge on one operation,
        differing only in terminality.
        """
        path = tmp_path / "out.jsonl"
        prepared = prepare_write(path, mode="append")

        with file_write_session(prepared) as session:
            assert session.operation == prepared.operation
