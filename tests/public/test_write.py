# vim: sw=4:ts=4:expandtab
"""Provides public tests for write targets and for writing and exporting items."""

from __future__ import annotations

import json
import re
from io import BytesIO
from typing import TYPE_CHECKING, cast

import pytest

from riko import export
from riko.base._exceptions import InvalidPipelineError, UnsupportedTargetError
from riko.definitions._nodes import ModuleNode, StreamEdge, WriteNode
from riko.definitions._targets import FileTarget
from riko.definitions._workflow_definition import Workflow
from riko.definitions._write import WriteCapabilities, WriteMode
from riko.io._async import async_write
from riko.modules.fetchdata import pipe as fetchdata_pipe
from riko.modules.write import async_pipe, pipe
from riko.runtime._export import list_formats
from riko.runtime._pipeline import Pipeline
from riko.types._enums import Formats
from riko.types._workflow import Endpoint
from riko.types.modules import WriteConf
from tests import async_test, is_installed, run_python
from tests._lifecycle import EXPECTED, ITEMS, VALUE, tokenized
from tests._targets import RecordStore

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from riko.types._streams import Item


_SEEDED_SET_WRITE = """
import sys
from riko.modules.write import pipe
items = [{"tags": {"alpha", "beta", "gamma", "delta"}}]
list(pipe(items, conf={"dest": sys.argv[1], "fmt": sys.argv[2]}))
"""

WRITE_NODE_PENDING = pytest.mark.xfail(
    strict=True, raises=InvalidPipelineError, reason="write nodes do not execute yet"
)

JSON_BYTES = b'[{"x": 0}, {"x": 1}, {"x": 2}]'

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


PARITY_WRITES = [
    pytest.param("json", JSON_BYTES, id="json"),
    pytest.param("csv", b"x\r\n0\r\n1\r\n2\r\n", id="csv"),
]


SKIPPED_TARGETS = [
    pytest.param({"fmt": "bogus"}, id="bogus"),
    pytest.param({"fmt": "list"}, id="list"),
    pytest.param({"fmt": "tuple"}, id="tuple"),
    pytest.param({"fmt": "json", "dest": None}, id="missing-dest"),
]


def _skipped_conf(path, conf) -> WriteConf:
    """Builds an unwritable conf aimed at ``path`` (``dest: None`` drops it)."""
    target = {"dest": path} | conf
    return cast("WriteConf", {k: v for k, v in target.items() if v is not None})


FINANCE_WRITES = [
    pytest.param("ofx", b"<OFX>", id="ofx"),
    pytest.param("qif", b"!Account", id="qif"),
]


class TestWrite:
    @pytest.mark.finance
    @pytest.mark.parametrize(("fmt", "marker"), FINANCE_WRITES)
    def test_write_module_writes_transactions(self, tmp_path, fmt, marker):
        path = tmp_path / f"out.{fmt}"
        list(pipe(TRANSACTIONS, conf=WriteConf({"dest": path, "fmt": fmt})))
        assert marker in path.read_bytes()

    @pytest.mark.finance
    @pytest.mark.parametrize(("fmt", "marker"), FINANCE_WRITES)
    @async_test
    async def test_async_write_module_writes_transactions(self, tmp_path, fmt, marker):
        path = tmp_path / f"out.{fmt}"
        result = async_pipe(TRANSACTIONS, conf=WriteConf({"dest": path, "fmt": fmt}))
        _ = [item async for item in result]
        assert marker in path.read_bytes()

    def test_sync_preserves_sequence(self, tmp_path):
        conf = WriteConf({"dest": str(tmp_path / "out.json")})
        assert list(pipe(ITEMS, conf=conf)) == ITEMS

    @async_test
    async def test_async_preserves_sequence(self, tmp_path):
        conf = WriteConf({"dest": str(tmp_path / "out.json")})
        result = async_pipe(ITEMS, conf=conf)
        assert [item async for item in result] == ITEMS

    @async_test
    async def test_async_source_is_written(self, tmp_path):
        async def source() -> AsyncIterator[Item]:
            for item in ITEMS:
                yield item

        path = tmp_path / "out.json"
        result = async_pipe(source(), conf=WriteConf({"dest": path, "fmt": "json"}))
        assert [item async for item in result] == ITEMS
        assert path.read_bytes() == JSON_BYTES

    @pytest.mark.parametrize(("fmt", "expected"), PARITY_WRITES)
    @async_test
    async def test_sync_and_async_write_identical_bytes(self, tmp_path, fmt, expected):
        sync_path, async_path = tmp_path / f"sync.{fmt}", tmp_path / f"async.{fmt}"
        list(pipe(ITEMS, conf=WriteConf({"dest": sync_path, "fmt": fmt})))
        conf = WriteConf({"dest": async_path, "fmt": fmt})
        _ = [item async for item in async_pipe(ITEMS, conf=conf)]
        assert sync_path.read_bytes() == expected
        assert async_path.read_bytes() == expected

    @pytest.mark.parametrize(
        ("fmt", "expected"),
        [
            ("json", b'[{"a": {"b": [1, {"c": 2}]}}]'),
            ("jsonl", b'{"a": {"b": [1, {"c": 2}]}}'),
        ],
    )
    def test_nested_dotdict_items(self, tmp_path, fmt, expected):
        source = tmp_path / "nested.json"
        source.write_text('[{"a": {"b": [1, {"c": 2}]}}]')
        items = list(fetchdata_pipe(conf={"url": source.as_uri()}))
        path = tmp_path / f"out.{fmt}"
        list(pipe(items, conf=WriteConf({"dest": path, "fmt": fmt})))
        assert path.read_bytes().strip() == expected

    def test_set_values_are_written_sorted_under_any_hash_seed(self, tmp_path):
        def write(seed: str) -> bytes:
            path = tmp_path / f"{seed}.json"
            run_python("-c", _SEEDED_SET_WRITE, str(path), "json", hash_seed=seed)
            return path.read_bytes()

        expected = b'"tags": ["alpha", "beta", "delta", "gamma"]'
        assert all(expected in write(seed) for seed in ("1", "2"))

    @pytest.mark.parametrize("conf", SKIPPED_TARGETS)
    def test_sync_bad_target_skips_but_passes_through(self, tmp_path, conf):
        path = tmp_path / "out"
        assert list(pipe(ITEMS, conf=_skipped_conf(path, conf))) == ITEMS
        assert not path.exists()

    @pytest.mark.parametrize("conf", SKIPPED_TARGETS)
    @async_test
    async def test_async_bad_target_skips_but_passes_through(self, tmp_path, conf):
        path = tmp_path / "out"
        result = async_pipe(ITEMS, conf=_skipped_conf(path, conf))
        assert [item async for item in result] == ITEMS
        assert not path.exists()

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
        assert path.read_bytes() == JSON_BYTES

    def test_unknown_extension_fails(self, tmp_path, caplog):
        path = tmp_path / "out.dat"
        list(pipe(ITEMS, conf=WriteConf({"dest": path})))
        assert not path.exists()
        assert any("Invalid Formats: 'dat'" in r.message for r in caplog.records)


class TestPipelineWriteDefinition:
    """The ``write`` verb validates its destination when the node is declared."""

    def test_declares_the_resolved_format_and_mode(self, tmp_path):
        pipeline = Pipeline().write(tmp_path / "out.csv", mode="append")
        node = pipeline.workflow.nodes["write-1"]
        assert isinstance(node, WriteNode)
        assert (node.fmt, node.mode, node.keys) == (Formats.CSV, WriteMode.APPEND, ())

    def test_file_rejects_keys(self, tmp_path):
        with pytest.raises(ValueError, match="forbids 'keys'"):
            Pipeline().write(tmp_path / "out.csv", keys="x")

    def test_destination_rejects_module_arguments(self, tmp_path):
        with pytest.raises(TypeError, match="not both"):
            Pipeline().write(tmp_path / "out.csv", conf=WriteConf({}))

    @pytest.mark.xfail(
        strict=True,
        raises=pytest.fail.Exception,
        reason="the write module stays reachable until write nodes execute: write() "
        "without a destination chains that module instead of requiring a destination",
    )
    def test_requires_a_destination(self):
        with pytest.raises(TypeError):
            Pipeline().write()


@WRITE_NODE_PENDING
class TestPipelineWrite:
    """The ``write`` verb at the pipeline level, once a write node can run."""

    def test_passthrough_preserves_stream(self, tmp_path):
        pipeline = Pipeline().write(tmp_path / "out.json")
        assert list(pipeline(ITEMS)) == ITEMS

    def test_passthrough_reaches_a_target_without_a_path(self):
        assert list(Pipeline().write(RecordStore())(ITEMS)) == ITEMS

    def test_writes_mid_chain(self, tmp_path):
        path = tmp_path / "out.json"
        pipeline = Pipeline().write(path).tail(conf={"count": 1})
        assert list(pipeline(ITEMS)) == [{"x": 2}]
        assert path.read_bytes() == JSON_BYTES

    def test_replace_defers_truncation_until_consumed(self, tmp_path):
        path = tmp_path / "out.jsonl"
        path.write_bytes(b'{"old": 1}\n')
        pipeline = Pipeline().write(path, mode="replace")
        assert path.read_bytes() == b'{"old": 1}\n'
        list(pipeline(ITEMS))
        assert path.read_bytes() == b'{"x": 0}\n{"x": 1}\n{"x": 2}\n'

    def test_graceful_close_finalizes_prefix(self, tmp_path):
        path = tmp_path / "out.json"
        stream = Pipeline().write(path)(ITEMS)
        next(stream)
        stream.close()
        assert path.read_bytes() == b'[{"x": 0}]'

    def test_exception_aborts(self, tmp_path):
        def seed():
            yield ITEMS[0]
            raise RuntimeError("boom")

        path = tmp_path / "out.json"

        with pytest.raises(RuntimeError, match="boom"):
            list(Pipeline().write(path)(seed()))

        assert not path.exists()

    def test_csv_writes_the_header_once(self, tmp_path):
        path = tmp_path / "out.csv"
        list(Pipeline().write(path)(ITEMS))
        assert path.read_bytes() == b"x\r\n0\r\n1\r\n2\r\n"

    def test_composes_after_a_chain(self, tmp_path):
        path = tmp_path / "out.json"
        pipeline = Pipeline.from_module("sort") | Pipeline().write(path)
        assert list(pipeline(ITEMS)) == ITEMS
        assert path.read_bytes() == JSON_BYTES

    def test_jsonl_has_no_array(self, tmp_path):
        path = tmp_path / "out.jsonl"
        list(Pipeline().write(path)(ITEMS))
        assert path.read_bytes() == b'{"x": 0}\n{"x": 1}\n{"x": 2}\n'

    def test_leaf_write_produces_one_framed_document(self, tmp_path):
        path = tmp_path / "out.json"
        pipeline = Pipeline().hash(options={"assign": "h"}).write(path)
        assert len(list(pipeline(ITEMS))) == len(ITEMS)
        assert path.read_bytes().startswith(b"[")
        assert path.read_bytes().endswith(b"]")

    def test_write_does_not_rerun_preceding_module(self, tmp_path):
        hashed = Pipeline().hash(options={"assign": "h"})
        through = list(hashed.write(tmp_path / "out.json")(ITEMS))
        assert through == list(hashed(ITEMS))

    def test_non_file_target_execution_unsupported(self):
        pipeline = Pipeline().write(RecordStore())

        with pytest.raises(UnsupportedTargetError, match="RecordStore"):
            list(pipeline(ITEMS))

    @pytest.mark.xfail(
        strict=True,
        raises=InvalidPipelineError,
        reason="a write node that feeds no workflow output does not execute yet",
    )
    def test_a_write_node_off_every_output_path_still_writes(self, tmp_path):
        path = tmp_path / "out.json"
        nodes = [
            ModuleNode(id="a", name="sort"),
            WriteNode(id="w", name="write", backend="file", dest=str(path)),
        ]
        edge = StreamEdge(Endpoint("a", "out"), Endpoint("w", "in"))
        outputs = {"default": Endpoint("a", "out")}
        flow = Workflow(nodes=nodes, edges=[edge], outputs=outputs)
        flow.validate()
        assert list(Pipeline(flow)(ITEMS)) == ITEMS
        assert path.read_bytes() == JSON_BYTES


EXPORT_OPTIONS = [
    pytest.param("csv", {"mode": "w"}, "x,y\n1,2\n", id="csv-writer-mode"),
    pytest.param("csv", {"chunksize": 1}, "x,y\n1,2\n", id="csv-chunksize"),
    pytest.param("csv", {"skip_header": True}, "1,2\n", id="csv-converter"),
    pytest.param("json", {"encoding": "utf8"}, '[{"x": 1, "y": 2}]', id="json"),
]

WRITER_OPTIONS = [
    pytest.param("csv", {"encoding": "utf8"}, id="encoding"),
    pytest.param("csv", {"chunksize": None}, id="chunksize"),
    pytest.param("csv", {"length": 0}, id="length"),
    pytest.param("csv", {"bar_len": 50}, id="bar_len"),
    pytest.param("list", {"mode": "w"}, id="list"),
]


class TestFormats:
    def test_format_values(self):
        assert [f.value for f in Formats] == [
            "csv",
            "geojson",
            "json",
            "jsonl",
            "ofx",
            "qif",
        ]


class TestExportFormats:
    """``export`` serializes each format and routes its writer and converter options."""

    def test_member_and_string_export_identically(self):
        items = [{"a": 1}]
        assert (
            export(items, Formats.JSON).getvalue() == export(items, "json").getvalue()
        )

    @pytest.mark.parametrize(("type_", "kwargs", "expected"), EXPORT_OPTIONS)
    def test_routes_writer_and_converter_options(
        self, tmp_path, type_, kwargs, expected
    ):
        path = tmp_path / f"out.{type_}"
        export([{"x": 1, "y": 2}], type_, str(path), **kwargs)
        assert path.read_text() == expected

    def test_empty_geojson_is_a_featureless_collection(self, tmp_path):
        path = tmp_path / "out.geojson"
        export([], "geojson", str(path))
        collection = json.loads(path.read_text())
        assert collection["type"] == "FeatureCollection"
        assert collection["features"] == []

    def test_finance_targets_track_csv2ofx(self):
        """``ofx``/``qif`` formats appear only when the finance extra is present."""
        finance_targets = {"ofx", "qif"}
        targets = set(list_formats())

        if is_installed("csv2ofx"):
            assert finance_targets <= targets
        else:
            assert not (finance_targets & targets)

    @pytest.mark.parametrize(("type_", "kwargs"), WRITER_OPTIONS)
    def test_writer_option_without_a_destination_raises(self, type_, kwargs):
        with pytest.raises(TypeError, match=next(iter(kwargs))):
            export([{"x": 1}], type_, **kwargs)

    def test_rejects_unknown_format(self):
        msg = "Invalid export type: 'xml'. Expected one of list, tuple, csv"

        with pytest.raises(ValueError, match=re.escape(msg)):
            export([{"x": 1}], "xml")

    @pytest.mark.xfail(
        strict=True,
        raises=TypeError,
        reason="meza's records2csv writes the BOM as bytes into a text buffer",
    )
    def test_csv_bom_is_written_in_the_given_encoding(self, tmp_path):
        path = tmp_path / "out.csv"
        export([{"x": 1}], "csv", str(path), encoding="utf-16", bom=True)
        assert path.read_bytes().startswith("\ufeff".encode("utf-16"))


class TestExportPipeline:
    """``export`` accepts a ``Pipeline`` wherever it accepts a stream."""

    def test_pipeline_exports_its_items(self):
        pipeline = tokenized(VALUE)
        assert export(pipeline) == EXPECTED

    def test_pipeline_serializes(self):
        pipeline = tokenized(VALUE)
        lines = export(pipeline, Formats.CSV).getvalue().splitlines()
        assert lines == ["content", "once is 1x", "twice is 2x", "thrice is 3x"]


FINANCE_EXPORTS = [
    pytest.param("ofx", "DATA:OFXSGML", "<STMTTRN>", len(TRANSACTIONS), id="ofx-txns"),
    pytest.param("qif", "!Account", "Checking", 1, id="qif-account-header"),
]


@pytest.mark.finance
class TestExportFinance:
    """The ``ofx``/``qif`` formats, available only with the ``finance`` extra."""

    @pytest.mark.parametrize(("fmt", "prefix", "fragment", "count"), FINANCE_EXPORTS)
    def test_export_serializes_transactions(self, fmt, prefix, fragment, count):
        text = "".join(export(TRANSACTIONS, fmt))
        assert text.startswith(prefix)
        assert text.count(fragment) == count


ASYNC_WRITE_ITERABLES = [
    pytest.param(["a", "b"], "w", 2, b"ab", id="str-list"),
    pytest.param(iter(["a", "b"]), "w", 2, b"ab", id="str-iterator"),
    pytest.param([b"a", b"b"], "wb", 2, b"ab", id="bytes-list"),
    pytest.param(iter(["a", "é"]), "wb", 3, "aé".encode(), id="str-iterator-binary"),
    pytest.param(iter([b"a", b"b"]), "w", 2, b"ab", id="bytes-iterator-text"),
]


SPLIT_MULTIBYTE_WRITES = [
    pytest.param(iter([b"h\xc3", b"\xa9llo"]), None, id="iterator"),
    pytest.param("héllo".encode(), 2, id="bytes"),
    pytest.param(BytesIO("héllo".encode()), 2, id="bytes-io"),
]


class TestAsyncWriteIterables:
    """``async_write`` writes each ``str``/``bytes`` element of an iterable."""

    @pytest.mark.parametrize(
        ("content", "mode", "written", "expected"), ASYNC_WRITE_ITERABLES
    )
    @async_test
    async def test_async_write_writes_every_element(
        self, tmp_path, content, mode, written, expected
    ):
        path = tmp_path / "out.txt"
        assert await async_write(path, content, mode=mode) == written
        assert path.read_bytes() == expected

    @pytest.mark.parametrize(("content", "chunksize"), SPLIT_MULTIBYTE_WRITES)
    @async_test
    async def test_decodes_a_character_split_across_chunks(
        self, tmp_path, content, chunksize
    ):
        path = tmp_path / "out.txt"
        assert await async_write(path, content, mode="w", chunksize=chunksize) == 5
        assert path.read_text(encoding="utf-8") == "héllo"


class TestWriteMode:
    def test_mode_values(self):
        assert [m.value for m in WriteMode] == ["append", "merge", "replace", "delete"]


class TestWriteCapabilities:
    def test_appendable_derived_from_modes(self):
        appendable = WriteCapabilities(modes=frozenset({WriteMode.APPEND}))
        unappendable = WriteCapabilities(modes=frozenset({WriteMode.REPLACE}))

        assert appendable.appendable is True
        assert unappendable.appendable is False

    def test_serializes_derived_from_format(self):
        serializing = WriteCapabilities(modes=frozenset(), fmt=Formats.CSV)
        native = WriteCapabilities(modes=frozenset())

        assert serializing.serializes is True
        assert native.serializes is False

    def test_keyed_modes_is_union(self):
        caps = WriteCapabilities(
            modes=frozenset(WriteMode),
            match_keyed_modes=frozenset({WriteMode.MERGE}),
            idempotent_modes=frozenset({WriteMode.APPEND}),
        )

        assert caps.keyed_modes == frozenset({WriteMode.MERGE, WriteMode.APPEND})

    def test_mode_sets_are_frozen_copies_of_the_input(self):
        modes, keyed = {WriteMode.APPEND, WriteMode.MERGE}, {WriteMode.MERGE}
        caps = WriteCapabilities(modes=modes, match_keyed_modes=keyed)
        modes.clear()
        keyed.add(WriteMode.APPEND)

        expected = WriteCapabilities(
            modes=frozenset({WriteMode.APPEND, WriteMode.MERGE}),
            match_keyed_modes=frozenset({WriteMode.MERGE}),
        )
        assert caps == expected
        assert hash(caps) == hash(expected)

    def test_keyed_modes_must_be_subset_of_modes(self):
        with pytest.raises(ValueError, match="not present in modes"):
            WriteCapabilities(
                modes=frozenset({WriteMode.REPLACE}),
                match_keyed_modes=frozenset({WriteMode.MERGE}),
            )

    def test_match_and_idempotent_must_not_overlap(self):
        with pytest.raises(ValueError, match="must not overlap"):
            WriteCapabilities(
                modes=frozenset({WriteMode.MERGE}),
                match_keyed_modes=frozenset({WriteMode.MERGE}),
                idempotent_modes=frozenset({WriteMode.MERGE}),
            )


class TestFileTarget:
    @pytest.mark.parametrize(
        ("dest", "appendable", "incremental"),
        [("out.csv", True, True), ("out.geojson", False, False)],
    )
    def test_target_owns_format_behavior(self, dest, appendable, incremental):
        capabilities = FileTarget(dest).get_capabilities()

        assert capabilities.serializes is True
        assert capabilities.appendable is appendable
        assert (WriteMode.APPEND in capabilities.modes) is appendable
        assert capabilities.incremental is incremental
        assert WriteMode.REPLACE in capabilities.modes
