# vim: sw=4:ts=4:expandtab
"""Provides public tests for writing and exporting a ``Pipeline``'s items."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, cast

import pytest

from riko import export
from riko.base._exceptions import UnsupportedTargetError
from riko.base._paths import ROOT_DIR
from riko.definitions._nodes import WriteNode
from riko.definitions._write import WriteCapabilities, WriteMode
from riko.modules.write import async_pipe, pipe
from riko.parsing._dotdict import DotDict
from riko.runtime._pipeline import Pipeline
from riko.types._enums import Backends, Formats
from riko.types.modules import ItemBuilderConf, ParsedParam, WriteConf
from tests import async_test, skipif_issync

if TYPE_CHECKING:
    from riko.types._streams import Items

WRITE_NODE_PENDING = pytest.mark.xfail(
    strict=True, reason="write nodes do not execute yet"
)

VALUE = "once is 1x,twice is 2x,thrice is 3x"
BUILDER_CONF = ItemBuilderConf(
    {"attrs": ParsedParam({"key": "content", "value": VALUE})}
)

EXPECTED = [
    {"content": "once is 1x"},
    {"content": "twice is 2x"},
    {"content": "thrice is 3x"},
]

ITEMS = [{"x": 0}, {"x": 1}, {"x": 2}]


class TestWritePassthrough:
    """``write`` yields every input item unchanged, in order."""

    def test_sync_preserves_sequence(self, tmp_path):
        conf = WriteConf({"dest": str(tmp_path / "out.json")})
        assert list(pipe(ITEMS, conf=conf)) == ITEMS

    @async_test
    async def test_async_preserves_sequence(self, tmp_path):
        conf = WriteConf({"dest": str(tmp_path / "out.json")})
        result = async_pipe(ITEMS, conf=conf)
        assert [item async for item in result] == ITEMS


@skipif_issync
class TestWriteParity:
    """The sync and async parsers serialize identical bytes."""

    @pytest.mark.anyio
    async def test_json_parity(self, tmp_path):
        sync_path, async_path = tmp_path / "sync.json", tmp_path / "async.json"
        list(pipe(ITEMS, conf=WriteConf({"dest": sync_path, "fmt": "json"})))
        conf = WriteConf({"dest": async_path, "fmt": "json"})
        _ = [item async for item in async_pipe(ITEMS, conf=conf)]
        expected = b'[{"x": 0}, {"x": 1}, {"x": 2}]'
        assert sync_path.read_bytes() == expected
        assert async_path.read_bytes() == expected

    @pytest.mark.anyio
    async def test_csv_parity(self, tmp_path):
        sync_path, async_path = tmp_path / "sync.csv", tmp_path / "async.csv"
        list(pipe(ITEMS, conf=WriteConf({"dest": sync_path, "fmt": "csv"})))
        conf = WriteConf({"dest": async_path, "fmt": "csv"})
        _ = [item async for item in async_pipe(ITEMS, conf=conf)]
        sync_bytes = sync_path.read_bytes()
        assert sync_bytes == async_path.read_bytes()
        assert sync_bytes.split() == [b"x", b"0", b"1", b"2"]


class TestWriteNestedItems:
    """Items holding nested mappings, as module output does, serialize to JSON."""

    @pytest.mark.parametrize(
        ("fmt", "expected"),
        [
            ("json", b'[{"a": {"b": [1, {"c": 2}]}}]'),
            ("jsonl", b'{"a": {"b": [1, {"c": 2}]}}'),
        ],
    )
    def test_nested_dotdict_items(self, tmp_path, fmt, expected):
        items: Items = [DotDict({"a": {"b": [1, {"c": 2}]}})]
        path = tmp_path / f"out.{fmt}"
        list(pipe(items, conf=WriteConf({"dest": path, "fmt": fmt})))
        assert path.read_bytes().strip() == expected


_SEEDED_SET_WRITE = """
import sys
from riko.modules.write import pipe
items = [{"tags": {"alpha", "beta", "gamma", "delta"}}]
list(pipe(items, conf={"dest": sys.argv[1], "fmt": sys.argv[2]}))
"""


class TestWriteSetValues:
    """Set values serialize in a stable sorted order."""

    @pytest.mark.parametrize("fmt", ["json", "jsonl"])
    def test_set_values_are_written_sorted_under_any_hash_seed(self, tmp_path, fmt):
        def write(seed: str) -> bytes:
            path = tmp_path / f"{seed}.{fmt}"
            args = [sys.executable, "-c", _SEEDED_SET_WRITE, str(path), fmt]
            env = {**os.environ, "PYTHONHASHSEED": seed}
            subprocess.run(args, check=True, cwd=ROOT_DIR, env=env)
            return path.read_bytes()

        expected = b'"tags": ["alpha", "beta", "delta", "gamma"]'
        assert all(expected in write(seed) for seed in ("1", "2", "3"))


class TestWriteSkips:
    """Unwritable configurations degrade: nothing is written, items pass through."""

    @pytest.mark.parametrize("fmt", ["bogus", "list", "tuple"])
    def test_sync_bad_target_skips_but_passes_through(self, tmp_path, fmt):
        path = tmp_path / "out"
        conf = cast("WriteConf", {"dest": path, "fmt": fmt})
        assert list(pipe(ITEMS, conf=conf)) == ITEMS
        assert not path.exists()

    @pytest.mark.parametrize("fmt", ["bogus", "list", "tuple"])
    @async_test
    async def test_async_bad_target_skips_but_passes_through(self, tmp_path, fmt):
        path = tmp_path / "out"
        conf = WriteConf({"dest": path, "fmt": fmt})
        result = async_pipe(ITEMS, conf=conf)
        assert [item async for item in result] == ITEMS
        assert not path.exists()

    def test_sync_missing_dest_skips_but_passes_through(self):
        conf = cast("WriteConf", {"fmt": "json"})
        assert list(pipe(ITEMS, conf=conf)) == ITEMS

    @async_test
    async def test_async_missing_dest_skips_but_passes_through(self):
        conf = cast("WriteConf", {"fmt": "json"})
        result = async_pipe(ITEMS, conf=conf)
        assert [item async for item in result] == ITEMS


class TestWriteTargetFromExtension:
    """When ``fmt`` is omitted, the dest extension selects the converter."""

    def test_sync_csv_extension(self, tmp_path):
        path = tmp_path / "out.csv"
        list(pipe(ITEMS, conf=WriteConf({"dest": path})))
        assert path.read_bytes().split() == [b"x", b"0", b"1", b"2"]

    @async_test
    async def test_async_csv_extension(self, tmp_path):
        path = tmp_path / "out.csv"
        result = async_pipe(ITEMS, conf=WriteConf({"dest": path}))
        _ = [item async for item in result]
        assert path.read_bytes().split() == [b"x", b"0", b"1", b"2"]

    def test_explicit_target_overrides_extension(self, tmp_path):
        path = tmp_path / "out.csv"
        list(pipe(ITEMS, conf=WriteConf({"dest": path, "fmt": "json"})))
        assert path.read_bytes() == b'[{"x": 0}, {"x": 1}, {"x": 2}]'

    def test_unknown_extension_fails(self, tmp_path, caplog):
        path = tmp_path / "out.dat"
        list(pipe(ITEMS, conf=WriteConf({"dest": path})))
        assert not path.exists()
        assert any("Invalid Formats: 'dat'" in r.message for r in caplog.records)


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


class TestPipelineWriteDefinition:
    """The ``write`` verb validates its destination when the node is declared."""

    def test_file_rejects_keys(self, tmp_path):
        with pytest.raises(ValueError, match="forbids 'keys'"):
            Pipeline(source=ITEMS).write(tmp_path / "out.csv", keys="x")

    def test_destination_rejects_module_arguments(self, tmp_path):
        with pytest.raises(TypeError, match="not both"):
            Pipeline(source=ITEMS).write(tmp_path / "out.csv", conf=WriteConf({}))

    def test_declares_the_resolved_format_and_mode(self, tmp_path):
        pipeline = Pipeline(source=ITEMS).write(tmp_path / "out.csv", mode="append")
        node = pipeline.workflow.nodes["write-1"]
        assert isinstance(node, WriteNode)
        assert (node.fmt, node.mode, node.keys) == (Formats.CSV, WriteMode.APPEND, ())

    @pytest.mark.xfail(
        strict=True,
        reason="the write module stays reachable until write nodes execute: write() "
        "without a destination chains that module instead of requiring a destination",
    )
    def test_requires_a_destination(self):
        with pytest.raises(TypeError):
            Pipeline(source=ITEMS).write()


@WRITE_NODE_PENDING
class TestPipelineWrite:
    """The ``write`` verb at the pipeline level, once a write node can run."""

    def test_passthrough_preserves_stream(self, tmp_path):
        pipeline = Pipeline(source=ITEMS).write(tmp_path / "out.json")
        assert list(pipeline) == ITEMS

    def test_passthrough_reaches_a_target_without_a_path(self):
        assert list(Pipeline(source=ITEMS).write(_RecordStore())) == ITEMS

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

        with pytest.raises(UnsupportedTargetError, match="_RecordStore"):
            list(pipeline)

    def test_write_does_not_rerun_preceding_module(self, tmp_path):
        once = list(Pipeline(source=ITEMS).hash(options={"assign": "h"}))
        source = Pipeline(source=ITEMS).hash(options={"assign": "h"})
        through = list(source.write(tmp_path / "out.json"))
        assert through == once


class TestExportFormats:
    """``Formats`` members mirror the ``export`` converters."""

    def test_member_and_string_export_identically(self):
        items = [{"a": 1}]
        assert (
            export(items, Formats.JSON).getvalue() == export(items, "json").getvalue()
        )


class TestExportPipeline:
    """``export`` accepts a ``Pipeline`` wherever it accepts a stream."""

    def test_pipeline_exports_its_items(self):
        source = Pipeline.from_module("itembuilder", conf=BUILDER_CONF)
        pipeline = source.tokenizer(options={"emit": True})
        assert export(pipeline) == EXPECTED

    def test_pipeline_serializes(self):
        source = Pipeline.from_module("itembuilder", conf=BUILDER_CONF)
        pipeline = source.tokenizer(options={"emit": True})
        lines = export(pipeline, Formats.CSV).getvalue().splitlines()
        assert lines == ["content", "once is 1x", "twice is 2x", "thrice is 3x"]


TRANSACTIONS = [
    {
        "Account": "Checking",
        "Date": "2024-01-01",
        "Amount": "100.00",
        "Description": "Acme",
        "Reference": "Widget",
        "Row": "1",
    },
    {
        "Account": "Checking",
        "Date": "2024-01-02",
        "Amount": "-50.00",
        "Description": "Store",
        "Reference": "Refund",
        "Row": "2",
    },
]


@pytest.mark.finance
class TestExportFinance:
    """The ``ofx``/``qif`` formats, available only with the ``finance`` extra."""

    def test_export_ofx_serializes_transactions(self):
        """``export(..., Formats.OFX)`` serializes an OFX document, one txn per item."""
        ofx = "".join(export(TRANSACTIONS, Formats.OFX))
        assert "<OFX>" in ofx
        assert ofx.count("<STMTTRN>") == len(TRANSACTIONS)

    def test_export_qif_serializes_transactions(self):
        """``export(..., Formats.QIF)`` emits a QIF document for the transactions."""
        qif = "".join(export(TRANSACTIONS, Formats.QIF))
        assert qif.startswith("!Account")
        assert "Checking" in qif
