# vim: sw=4:ts=4:expandtab
"""Tests the stable ``export`` verb and the ``Formats`` catalog it is keyed by."""

from riko import Pipeline, export
from riko.io._serialization import CONVERSION_FUNCS
from riko.types._enums import Formats
from riko.types.modules import ItemBuilderConf, ParsedParam

_VALUE = "once is 1x,twice is 2x,thrice is 3x"
_ATTRS = ParsedParam({"key": "content", "value": _VALUE})
BUILDER_CONF = ItemBuilderConf({"attrs": _ATTRS})

EXPECTED = [
    {"content": "once is 1x"},
    {"content": "twice is 2x"},
    {"content": "thrice is 3x"},
]


class TestExportFormats:
    """``Formats`` members mirror the ``export`` converter registry."""

    def test_member_and_string_export_identically(self):
        items = [{"a": 1}]
        assert (
            export(items, Formats.JSON).getvalue() == export(items, "json").getvalue()
        )

    def test_every_converter_has_a_member(self):
        assert set(CONVERSION_FUNCS) <= set(Formats)


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
