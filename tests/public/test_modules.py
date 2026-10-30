# vim: sw=4:ts=4:expandtab
"""Provides public tests for built-in modules, module discovery, and import surfaces."""

from __future__ import annotations

import gc
import sqlite3
from collections.abc import AsyncIterator, Iterator, Mapping
from datetime import datetime, timedelta, timezone
from inspect import isawaitable
from itertools import count
from time import struct_time
from typing import TYPE_CHECKING, Any

import pytest

from riko.bado._util import maybe_aclosing
from riko.bado.itertools import alist
from riko.base._paths import get_path
from riko.coercion import cast as cast_module
from riko.definitions._context import Context
from riko.ext.codegen import (
    NameEntry,
    enum_member_name,
    gen_catalog_entries,
    generate_module_names,
)
from riko.modules._decorators import operator, processor, splitter
from riko.modules._metadata import get_module_metadata, list_modules
from riko.modules.aggregate import async_pipe as async_aggregate_pipe
from riko.modules.aggregate import pipe as aggregate_pipe
from riko.modules.fetchdata import async_pipe as async_fetchdata_pipe
from riko.modules.fetchdata import pipe as fetchdata_pipe
from riko.modules.filter import pipe as filter_pipe
from riko.modules.input import pipe as input_pipe
from riko.modules.join import pipe as join_pipe
from riko.modules.receive import pipe as receive_pipe
from riko.modules.regex import pipe as regex
from riko.modules.rename import pipe as rename
from riko.modules.send import pipe as send_pipe
from riko.modules.slugify import pipe as slugify_pipe
from riko.modules.sort import pipe as sort_pipe
from riko.modules.timeout import async_pipe as timeout_async_pipe
from riko.modules.udf import pipe as udf_pipe
from riko.modules.xpathfetchpage import pipe as xpathfetchpage
from riko.runtime._pipeline import Pipeline
from riko.types._enums import CastType, SortableCastType
from riko.types.modules import (
    FilterConf,
    FilterConfRule,
    InputConf,
    JoinConf,
    RegexConf,
    RegexConfRule,
    RenameConf,
    RenameConfRule,
    SortConf,
    SortConfRule,
    XpathFetchPageConf,
)
from tests import async_test
from tests._lifecycle import LOOKAHEAD
from tests._loopback import loopback_url

if TYPE_CHECKING:
    from collections.abc import AsyncIterable
    from pathlib import Path

    from riko.types._streams import Item

_OMITTED = object()
_NUMBERS = ["1", "2", "3"]
_DATES = ["2019-01-01", "2020-05-01", "2024-11-12"]

FETCH_MODULES = [
    "fetch",
    "fetchdata",
    "fetchpage",
    "fetchsitefeed",
    "fetchtable",
    "fetchtext",
]

MISSING_URL = "file:///nonexistent.xml"
JSON = b'{"items": [{"title": "A"}, {"title": "B"}]}'
XML = b"<root><items><title>A</title></items><items><title>B</title></items></root>"


def _values(stream: Any, key: str) -> list[Any]:
    return [item.get(key) for item in stream]


class TestInput:
    def test_input_test_flag_scoped_to_test_context(self, monkeypatch):
        """
        Limit the auto-wired test flag to test contexts.

        Non-test contexts must still prompt for input.
        """
        monkeypatch.setattr("builtins.input", lambda *args: "typed")
        conf = InputConf({"prompt": "?", "default": "def", "type": CastType.TEXT})

        assert next(input_pipe(conf=conf, context=Context(test=True))) == "def"
        assert next(input_pipe(conf=conf, context=Context(test=False))) == "typed"
        assert next(input_pipe(conf=conf)) == "typed"

    def test_input_empty_inputs_uses_default(self, monkeypatch):
        monkeypatch.setattr(
            "builtins.input", lambda *args: pytest.fail("input() should not be called")
        )
        conf = InputConf({"prompt": "?", "default": "def", "type": CastType.TEXT})

        assert next(input_pipe(conf=conf, inputs={})) == "def"
        assert next(input_pipe(conf=conf, context=Context(inputs={}))) == "def"
        assert Context().inputs is None

    def test_input_conf_test_flag_uses_default(self, monkeypatch):
        monkeypatch.setattr(
            "builtins.input", lambda *args: pytest.fail("input() should not be called")
        )
        conf = InputConf(
            {"prompt": "How old are you?", "type": CastType.INT, "test": True}
        )
        assert next(input_pipe(conf=conf)) == 0


class TestFetchModules:
    @pytest.mark.parametrize("name", FETCH_MODULES)
    def test_an_unopenable_url_raises(self, name):
        pipeline = Pipeline.from_module(name, conf={"url": MISSING_URL})

        with pytest.raises(OSError, match="No such file"):
            list(pipeline)

    @pytest.mark.parametrize("name", FETCH_MODULES)
    @async_test
    async def test_an_unopenable_url_raises_asynchronously(self, name):
        pipeline = Pipeline.from_module(name, conf={"url": MISSING_URL})

        with pytest.raises(OSError, match="No such file"):
            await alist(pipeline)


async def _titles(conf):
    stream = async_fetchdata_pipe(conf=conf)
    return [item.get("title") async for item in stream]


class TestFetchdata:
    """``fetchdata`` infers the parser for extensionless URLs and local documents."""

    @pytest.mark.parametrize(
        ("content", "content_type"), [(JSON, "application/json"), (XML, "text/xml")]
    )
    @pytest.mark.simulated_network
    @async_test
    async def test_file_contents(self, content, content_type):
        with loopback_url(content, content_type=content_type, path="data") as url:
            result = await _titles({"url": url, "path": "items"})

        assert result == ["A", "B"]

    @async_test
    async def test_without_a_path_yields_the_whole_document(self, tmp_path):
        path = tmp_path / "data.json"
        path.write_bytes(JSON)
        stream = async_fetchdata_pipe(conf={"url": path.as_uri()})
        items = [item async for item in stream]
        assert items == list(fetchdata_pipe(conf={"url": path.as_uri()}))
        assert items

    def test_minified_xml_parses(self, tmp_path):
        path = tmp_path / "data.xml"
        path.write_bytes(XML)
        items = fetchdata_pipe(conf={"url": path.as_uri(), "path": "items"})
        assert [item.get("title") for item in items] == ["A", "B"]

    @pytest.mark.xfail(
        strict=True,
        reason="splitext keeps the query string in the extension ('json?token=abc'), "
        "so the JSON parser is never selected ",
    )
    @pytest.mark.simulated_network
    @async_test
    async def test_query_string_does_not_defeat_extension(self):
        """Detect URL formats from extensions even when queries are present."""
        path = "export.json?token=abc"

        with loopback_url(JSON, content_type="application/json", path=path) as url:
            result = await _titles({"url": url, "path": "items"})

        assert result == ["A", "B"]

    @pytest.mark.xfail(
        strict=True,
        raises=UnicodeDecodeError,
        reason="owned by the pending encoding-precedence work: XML is decoded with "
        "the configured encoding instead of the encoding its declaration names",
    )
    def test_declared_encoding_is_honored(self, tmp_path):
        path = tmp_path / "latin1.xml"
        declaration = '<?xml version="1.0" encoding="ISO-8859-1"?>'
        text = f"{declaration}<r><items><t>café</t></items></r>"
        path.write_bytes(text.encode("latin-1"))
        items = fetchdata_pipe(conf={"url": path.as_uri(), "path": "items"})
        assert [item.get("t") for item in items] == ["café"]


@pytest.fixture
def sqlite_path(tmp_path: Path) -> Path:
    path = tmp_path / "cars.sqlite"
    connection = sqlite3.connect(path)

    try:
        connection.execute("CREATE TABLE t(make TEXT, mileage INT)")
        connection.execute("INSERT INTO t VALUES ('ford', 7213)")
        connection.commit()
    finally:
        connection.close()

    return path


class TestFetchtable:
    @pytest.mark.xfail(
        strict=True,
        raises=(TypeError, UnicodeDecodeError),
        reason="owned by the connectors work: fetchtable forwards the csv-only"
        " delimiter option to the sqlite reader (TypeError) and opens the binary"
        " source as text (UnicodeDecodeError); xlsx follows the same path",
    )
    @pytest.mark.filterwarnings("ignore::ResourceWarning")
    def test_fetchtable_reads_sqlite_fixture(self, sqlite_path: Path):
        """Ensure binary tabular sources open in binary mode and yield rows."""
        pipeline = Pipeline.from_module("fetchtable", conf={"url": str(sqlite_path)})
        item, failure = None, None

        try:
            item = pipeline.first()
        except (TypeError, UnicodeDecodeError) as error:
            failure = type(error)(*error.args)

        # The failed read leaks its file handle; drop the traceback that pins it and
        # collect here so the warning fires under this test's filter, not after it ends.
        if failure is not None:
            gc.collect()
            raise failure

        assert isinstance(item, Mapping)
        assert item.get("make") == "ford"


class TestXpathfetchpage:
    def test_xpathfetchpage_strips_xhtml_namespace_from_nested_keys(self):
        conf = XpathFetchPageConf(
            {"url": get_path("users.jyu.fi.html"), "xpath": "/html/body/p/a"}
        )

        assert next(xpathfetchpage(conf=conf)) == {
            "href": "http://www.w3.org/",
            "img": {"src": "http://www.w3.org/Icons/w3c_home", "alt": "W3C"},
        }


# Numeric operands compare numerically; anything else, including a mixed pair and
# a non-finite value, compares as text.
ORDERED_COMPARES = [
    pytest.param(["9", "10"], "greater", "9", ["10"], id="numeric-strings"),
    pytest.param([9, 10], "greater", 9, [10], id="numbers"),
    pytest.param(["apple", "banana"], "greater", "apple", ["banana"], id="words"),
    pytest.param(["10", "apple"], "greater", "banana", [], id="mixed-is-text"),
    pytest.param(["nan", "5"], "greater", "9", ["nan"], id="nan-is-text"),
    pytest.param(["-inf"], "less", "-5", [], id="inf-is-text"),
]


class TestFilter:
    @pytest.mark.parametrize(("values", "op", "value", "expected"), ORDERED_COMPARES)
    def test_filter_ordered_compare(self, values, op, value, expected):
        items = [{"x": x} for x in values]
        rule = FilterConfRule(field="x", op=op, value=value)
        conf = FilterConf({"rule": rule})
        assert _values(filter_pipe(items, conf=conf), "x") == expected

    def test_filter_relative_date_value_resolves_per_evaluation(self, monkeypatch):
        """A ``"today"`` rule value follows the clock, not its first evaluation."""
        ahead, behind = timezone(timedelta(hours=14)), timezone(timedelta(hours=-12))
        items = [{"x": datetime.now(behind).date().isoformat()}]
        rule = FilterConfRule(field="x", op="before", value="today")
        conf = FilterConf({"rule": rule})

        monkeypatch.setattr(cast_module, "load_local_tz", lambda **_: ahead)
        assert _values(filter_pipe(items, conf=conf), "x") == [items[0]["x"]]

        monkeypatch.setattr(cast_module, "load_local_tz", lambda **_: behind)
        assert _values(filter_pipe(items, conf=conf), "x") == []

    def test_filter_allow_inf_flag(self, monkeypatch):
        """Compare infinities numerically when ``ALLOW_INF`` is enabled."""
        items = [{"x": "-inf"}]
        conf = FilterConf({"rule": FilterConfRule(field="x", op="less", value="-5")})

        monkeypatch.setattr("riko.modules.filter.ALLOW_INF", True)
        assert _values(filter_pipe(items, conf=conf), "x") == ["-inf"]

        nan_rule = FilterConfRule(field="x", op="greater", value="9")
        nan_conf = FilterConf({"rule": nan_rule})
        assert _values(filter_pipe([{"x": "nan"}], conf=nan_conf), "x") == ["nan"]


class TestRename:
    def test_rename_skips_absent_field(self):
        """A rename rule naming an absent field leaves the item untouched."""
        conf = RenameConf({"rule": RenameConfRule(field="content", newval="greeting")})
        assert next(rename({"title": "hi"}, conf=conf)) == {"title": "hi"}

    def test_rename_renames_present_falsy_field(self):
        """A present-but-falsy value is still renamed (absent ≠ present-``None``)."""
        conf = RenameConf({"rule": RenameConfRule(field="content", newval="greeting")})
        assert next(rename({"content": ""}, conf=conf)) == {"greeting": ""}


class TestRegex:
    def test_regex_skips_absent_field(self):
        """A regex rule naming an absent field leaves the item untouched."""
        conf = RegexConf(
            {"rule": RegexConfRule(field="content", match="l", replace="L")}
        )
        assert next(regex({"title": "hi"}, conf=conf)) == {"title": "hi"}


SLUGIFY_CASES = [
    pytest.param("北京 市", "bei-jing-shi", id="han-transliteration"),
    pytest.param("ß straße", "ss-strasse", id="eszett-expansion"),
]


class TestSlugify:
    @pytest.mark.parametrize(("content", "slug"), SLUGIFY_CASES)
    def test_non_ascii_content_transliterates(self, content, slug):
        assert _values(slugify_pipe({"content": content}), "slugify") == [slug]


def _counting_source(consumed: list[int]) -> Any:
    for i in count():
        consumed.append(i)
        yield {"x": "foo", "i": i}


class TestJoin:
    def test_keyed_join_does_not_materialize_its_primary(self):
        """``other`` is the replayed side, so an unbounded primary must still emit."""
        consumed: list[int] = []
        other = [{"x": "bar", "c": 4}, {"x": "foo", "c": 5}]
        conf = JoinConf(join_key="x")
        joined = join_pipe(_counting_source(consumed), conf=conf, other=other)

        assert next(joined) == {"x": "foo", "i": 0, "c": 5}
        assert len(consumed) <= LOOKAHEAD
        assert next(joined) == {"x": "foo", "i": 1, "c": 5}
        assert len(consumed) <= 1 + LOOKAHEAD

    def test_natural_join_does_not_materialize_its_primary(self):
        """The keyless natural join is lazy in its primary stream too."""
        consumed: list[int] = []
        joined = join_pipe(_counting_source(consumed), other=[{"c": 5}])

        assert next(joined) == {"x": "foo", "i": 0, "c": 5}
        assert len(consumed) <= LOOKAHEAD


SORTABLE_VALUES = [
    pytest.param(SortableCastType.FLOAT, _NUMBERS, id="float"),
    pytest.param(SortableCastType.DECIMAL, _NUMBERS, id="decimal"),
    pytest.param(SortableCastType.DATE, _DATES, id="date"),
    pytest.param(SortableCastType.DATETIME, _DATES, id="datetime"),
]


class TestSort:
    @pytest.mark.parametrize("dir_", ["asc", "desc"])
    @pytest.mark.parametrize(("type_", "vals"), SORTABLE_VALUES)
    def test_sort_fillers_stay_orderable(self, dir_, type_, vals: list[str]):
        """
        An unparseable numeric field degrades to an orderable filler, not NaN.

        A missing field groups apart from it: first ascending, last descending,
        regardless of where either sat in the input.
        """
        rule = SortConfRule(field="n", dir=dir_, type=type_)
        conf = SortConf(rule=rule)

        if dir_ == "asc":
            expected = [None, "abc", *vals]
        else:
            expected = [*reversed(vals), "abc", None]

        mid = [
            {"n": vals[2]},
            {"x": "abc"},
            {"n": "abc"},
            {"n": vals[0]},
            {"n": vals[1]},
        ]
        first = [
            {"n": "abc"},
            {"x": "abc"},
            {"n": vals[2]},
            {"n": vals[0]},
            {"n": vals[1]},
        ]

        assert _values(sort_pipe(mid, conf=conf), "n") == expected
        assert _values(sort_pipe(first, conf=conf), "n") == expected

    def test_sort_missing_field_is_not_the_cast_default(self):
        """A missing numeric field groups first instead of sorting as ``0``."""
        items = [{"n": "3"}, {"x": "no number"}, {"n": "-5"}]
        conf = SortConf(rule=SortConfRule(field="n", type=SortableCastType.INT))

        assert _values(sort_pipe(items, conf=conf), "n") == [None, "-5", "3"]

    def test_sort_rule_default_sorts_missing_field_as_that_value(self):
        """A rule ``default`` stands in for the missing field, cast like a value."""
        items = [{"n": "3"}, {"x": "no number"}, {"n": "-5"}]
        rule = SortConfRule(field="n", type=SortableCastType.INT, default="0")
        conf = SortConf(rule=rule)

        assert _values(sort_pipe(items, conf=conf), "n") == ["-5", None, "3"]

    @pytest.mark.parametrize("dir_", ["asc", "desc"])
    def test_untyped_sort_groups_items_lacking_the_field(self, dir_):
        """An untyped rule never compares a missing-field filler with real values."""
        early = struct_time((2012, 5, 11, 10, 1, 0, 4, 132, 1))
        late = struct_time((2014, 8, 27, 2, 2, 12, 2, 239, 0))
        items = [{"d": late}, {"x": "no date"}, {"d": None}, {"d": early}]
        conf = SortConf(rule=SortConfRule(field="d", dir=dir_))

        if dir_ == "asc":
            expected = [None, None, early, late]
        else:
            expected = [late, early, None, None]

        assert _values(sort_pipe(items, conf=conf), "d") == expected


class TestSend:
    def test_send_populates_ids_when_given(self):
        """The explicit ``ids`` parameter records each target's delivery id."""
        receiver = receive_pipe(conf={"name": "id-target", "wait": 0.01, "max_wait": 2})
        next(receiver)
        ids: dict[str, int] = {}
        list(send_pipe([{"x": 0}], others=["id-target"], ids=ids))
        assert isinstance(ids.get("id-target"), int)


async def _agen_xs() -> AsyncIterator[Item]:
    for x in range(2):
        yield {"x": x}


async def _async_count(stream: AsyncIterable[Item]) -> list[Item]:
    return [{"n": len([item async for item in stream])}]


ASYNC_AGGREGATE_FUNCS = [
    pytest.param(lambda stream: [{"n": len(list(stream))}], id="sync-func-drained"),
    pytest.param(_async_count, id="async-func-async-stream"),
]


class TestAsyncAggregate:
    @pytest.mark.parametrize("func", ASYNC_AGGREGATE_FUNCS)
    @async_test
    async def test_async_source(self, func: object):
        """A sync func gets the collected items; an async func gets the async stream."""
        result = async_aggregate_pipe(_agen_xs(), func=func)
        assert [item async for item in result] == [{"n": 2}]


MISSING_OPERANDS = [
    pytest.param(udf_pipe, "func", _OMITTED, id="udf-omitted"),
    pytest.param(aggregate_pipe, "func", _OMITTED, id="aggregate-omitted"),
    pytest.param(join_pipe, "other", _OMITTED, id="join-omitted"),
    pytest.param(send_pipe, "others", _OMITTED, id="send-omitted"),
    pytest.param(udf_pipe, "func", 0, id="udf-empty"),
    pytest.param(aggregate_pipe, "func", 0, id="aggregate-empty"),
    pytest.param(join_pipe, "other", [], id="join-empty"),
    pytest.param(send_pipe, "others", [], id="send-empty"),
]


class TestRequiredOperands:
    @pytest.mark.parametrize(("pipe", "operand", "value"), MISSING_OPERANDS)
    def test_missing_operand_raises(self, pipe: Any, operand: str, value: object):
        """An omitted or empty operand is a call-site error that names the operand."""
        kwargs = {} if value is _OMITTED else {operand: value}

        with pytest.raises(TypeError, match=f"requires the {operand!r} keyword"):
            list(pipe([{"x": 0}], **kwargs))


NON_LOOPABLE_FILTERS = [
    pytest.param(None, "source", id="sources"),
    pytest.param("processor", None, id="processors"),
]


class TestListModules:
    def test_filter_non_loopable_modules(self):
        modules = list_modules(loopable=False, show_metadata=True)
        assert modules
        assert all(not module.loopable for module in modules)

        names = {module.name for module in modules}
        assert "input" in names
        assert "count" in names
        assert "split" in names
        assert "dateformat" not in names

    @pytest.mark.parametrize(("kind", "subtype"), NON_LOOPABLE_FILTERS)
    def test_filter_non_loopable_by_kind(self, kind: str | None, subtype: str | None):
        modules = list_modules(type=kind, subtype=subtype, loopable=False)
        assert modules == ["input"]

    def test_type_and_subtype_cannot_be_combined(self):
        with pytest.raises(ValueError, match="type and subtype cannot be combined"):
            list_modules(type="operator", subtype="composer")

    def test_primary_requires_subtype(self):
        with pytest.raises(ValueError, match="primary=True requires subtype"):
            list_modules(primary=True)


class TestModuleMetadata:
    """Derived module metadata and its classification."""

    def test_operator_metadata(self):
        metadata = get_module_metadata("count", strict=True)
        assert metadata.subtypes == {"aggregator", "composer"}
        assert metadata.has_sync
        assert metadata.has_async

    def test_processor_metadata(self):
        source = get_module_metadata("fetch", strict=True)
        transformer = get_module_metadata("dateformat", strict=True)

        assert source.type == "processor"
        assert source.subtype == "source"
        assert source.subtypes == {"source"}

        assert transformer.type == "processor"
        assert transformer.subtype == "transformer"
        assert transformer.subtypes == {"transformer"}

    def test_splitter_metadata(self):
        metadata = get_module_metadata("split", strict=True)
        assert metadata.type == "splitter"
        assert metadata.subtype == "splitter"
        assert metadata.subtypes == {"splitter"}

    def test_loopable_metadata(self):
        # processors are loopable (they transform a single item) ...
        assert get_module_metadata("dateformat", strict=True).loopable
        assert get_module_metadata("itembuilder", strict=True).loopable

        # ... except input, which prompts for interactive user input
        assert not get_module_metadata("input", strict=True).loopable

        # operators and splitters cannot be embedded in a loop
        assert not get_module_metadata("count", strict=True).loopable
        assert not get_module_metadata("split", strict=True).loopable

    def test_operator_metadata_is_derived(self):
        @operator()
        def value_pipe(*args: Any, **kwargs: object) -> int:
            return 1

        @operator()
        def mapping_pipe(*args: Any, **kwargs: object) -> dict[str, int]:
            return {"count": 1}

        @operator()
        def stream_pipe(*args: Any, **kwargs: object) -> Iterator[dict[str, int]]:
            yield {"count": 1}

        @operator()
        def composition_key_pipe(
            *args, count_key=None, **kwargs
        ) -> dict[str, int] | Iterator[dict[str, int]]:
            return iter([{"count": 1}]) if count_key else {"count": 1}

        assert value_pipe.subtype == "aggregator"
        assert value_pipe.subtypes == {"aggregator"}

        assert mapping_pipe.subtype == "aggregator"
        assert mapping_pipe.subtypes == {"aggregator"}

        assert stream_pipe.subtype == "composer"
        assert stream_pipe.subtypes == {"composer"}

        assert composition_key_pipe.subtype == "aggregator"
        assert composition_key_pipe.subtypes == {"aggregator", "composer"}

    def test_builtin_metadata_provider(self):
        assert get_module_metadata("fetch", strict=True).provider == "riko"

    def test_metadata_subtypes_are_frozen(self):
        metadata = get_module_metadata("fetch", strict=True)

        assert isinstance(metadata.subtypes, frozenset)
        assert metadata.subtypes == {"source"}

    def test_unknown_module_metadata_raises_when_strict(self):
        with pytest.raises(ValueError, match="has no metadata"):
            get_module_metadata("not_a_builtin_module", strict=True)


def _create_wrapper(name: str, *, iscoro: bool, isasync: bool):
    """Decorate a fresh function with the given name/awaitability/explicit flag."""

    async def _coro(item, extraction, objconf, **kwargs) -> str:
        return str(item["content"]).upper()

    def _sync(item, extraction, objconf, **kwargs) -> str:
        return str(item["content"]).upper()

    fn = _coro if iscoro else _sync
    fn.__name__ = name
    decorate = processor(isasync=True) if isasync else processor()
    return decorate(fn)


def _record_test_flag(seen: list[object]):
    def record(item: Item, *args, **kwargs) -> str:
        seen.append(kwargs.get("test"))
        return "seen"

    return record


def _skip_marked(item: Item, *args, **kwargs) -> str:
    return "processed"


ISASYNC_CASES = [
    pytest.param("pipe", False, False, False, id="sync-pipe"),
    pytest.param("async_pipe", False, False, True, id="sync-async_pipe-name"),
    pytest.param("async_pipe", True, False, True, id="async_def-async_pipe"),
    pytest.param("shout", True, False, True, id="async_def-other-name"),
    pytest.param("shout", False, False, False, id="sync-other-name"),
    pytest.param("shout", False, True, True, id="explicit-required"),
    pytest.param("async_pipe", False, True, True, id="explicit-redundant-name"),
    pytest.param("shout", True, True, True, id="explicit-redundant-async"),
]


ASYNC_NAMED_PIPES = [
    pytest.param(True, False, "an async def", id="async_def"),
    pytest.param(False, True, "marked isasync=True", id="isasync=True"),
    pytest.param(True, True, "an async def", id="async_def+isasync=True"),
]


FOREIGN_OPTIONS = [
    pytest.param(processor, "embed", True, id="processor+embed"),
    pytest.param(operator, "skip_if", True, id="operator+skip_if"),
    pytest.param(splitter, "pollable", True, id="splitter+pollable"),
    pytest.param(splitter, "emit", True, id="splitter+emit"),
    pytest.param(splitter, "count", True, id="splitter+count"),
    pytest.param(splitter, "skip_if", True, id="splitter+skip_if"),
    pytest.param(splitter, "embed", True, id="splitter+embed"),
    pytest.param(processor, "count", "first", id="processor+count"),
    pytest.param(processor, "conf", "first", id="processor+conf"),
    pytest.param(processor, "bogus", "first", id="processor+bogus"),
    pytest.param(operator, "bogus", "first", id="operator+bogus"),
    pytest.param(operator, "resources", "first", id="operator+resources"),
    pytest.param(operator, "count", "first", id="operator+count"),
    pytest.param(operator, "embed", "first", id="operator+embed"),
    pytest.param(splitter, "bogus", "first", id="splitter+bogus"),
]


class TestProcessor:
    """A ``processor`` resolves its interface, keeps call flags, and skips items."""

    @pytest.mark.parametrize(("name", "iscoro", "isasync", "expected"), ISASYNC_CASES)
    def test_resolved_isasync(self, name, iscoro, isasync, expected):
        """
        Resolve ``isasync`` from the explicit flag, ``async def``, or the name.

        ``isasync`` marks which callable a pipe is (``pipe`` or ``async_pipe``),
        not whether the function is a coroutine, so it is only needed explicitly
        for a sync callable that serves as the ``async_pipe`` under another name.
        """
        assert _create_wrapper(name, iscoro=iscoro, isasync=isasync).isasync is expected

    def test_sync_list(self):
        seen: list[object] = []
        pipe = processor()(_record_test_flag(seen))
        list(pipe([{"a": 1}, {"a": 2}], test=True))
        assert seen == [True, True]

    def test_sync(self):
        pipe = processor(skip_if=lambda item: "x" in item)(_skip_marked)
        result = list(pipe([{"x": 1}, {"y": 2}], assign="y"))
        assert result == [{"x": 1}, {"y": "processed"}]

    @pytest.mark.parametrize(("iscoro", "isasync", "reason"), ASYNC_NAMED_PIPES)
    def test_async_named_pipe_raises(self, iscoro, isasync, reason):
        """A function named ``pipe`` that resolves async is a contradiction."""
        with pytest.raises(TypeError) as excinfo:
            _create_wrapper("pipe", iscoro=iscoro, isasync=isasync)

        message = str(excinfo.value)
        assert "'pipe' must be synchronous" in message
        assert "async_pipe" in message
        assert reason in message

    @pytest.mark.parametrize(("decorator", "option", "value"), FOREIGN_OPTIONS)
    def test_unsupported_option_raises(self, decorator, option, value):
        kwargs: dict[str, object] = {option: value}
        name = decorator.__name__

        with pytest.raises(
            TypeError, match=f"{name} modules do not support the '{option}'"
        ):
            decorator(**kwargs)


class TestAsyncProcessor:
    """An async ``processor`` keeps call flags and skips items."""

    @async_test
    async def test_async_list(self):
        seen: list[object] = []
        async_pipe = processor(isasync=True)(_record_test_flag(seen))
        _ = [item async for item in async_pipe([{"a": 1}, {"a": 2}], test=True)]
        assert seen == [True, True]

    @pytest.mark.timeout(1)
    @async_test
    async def test_async_sync_iterable_streams_before_exhaustion(self):
        """Keep an unbounded sync iterable from being read whole up front."""
        pulled: list[int] = []

        def unbounded():
            for index in count():
                if index > 1000:
                    raise RuntimeError("the source was read past 1000 items")

                pulled.append(index)
                yield {"a": index}

        async_pipe = processor(isasync=True)(_record_test_flag([]))

        async with maybe_aclosing(async_pipe(unbounded(), test=True)) as stream:
            assert await anext(stream)
            assert len(pulled) <= 1000

    @async_test
    async def test_async(self):
        async_pipe = processor(isasync=True, skip_if=lambda item: "x" in item)(
            _skip_marked
        )
        stream = async_pipe([{"x": 1}, {"y": 2}], assign="y")
        result = [item async for item in stream]
        assert result == [{"x": 1}, {"y": "processed"}]


class TestAsyncOperator:
    """
    A decorated async operator returns an ``AsyncIterator`` without awaiting.

    The wrapper call boundary must never expose ``Awaitable[AsyncIterator]``,
    whatever the parser's implementation style, and an async-generator source
    flows through it.
    """

    @async_test
    async def test_feed_source_through_timeout(self):
        async def feed():
            for x in range(3):
                yield {"x": x}

        result = timeout_async_pipe(feed(), conf={})
        assert [item async for item in result] == [{"x": 0}, {"x": 1}, {"x": 2}]

    @async_test
    async def test_feed_reaches_parser_as_async_iterator(self):
        received = {}

        @operator(isasync=True)
        async def async_pipe(stream, objconf, tuples, **kwargs):
            received["is_async"] = isinstance(stream, AsyncIterator)
            collected = [item async for item in stream]
            return iter(collected)

        async def feed():
            for x in range(3):
                yield {"content": x}

        result = async_pipe(feed())
        expected = [{"content": 0}, {"content": 1}, {"content": 2}]
        assert [item async for item in result] == expected
        assert received["is_async"] is True

    @async_test
    async def test_sync_parser_operator_returns_async_iterator(self):
        items = [{"content": "a"}, {"content": "b"}]

        @operator(isasync=True)
        def async_pipe(stream, objconf, tuples, **kwargs):
            yield from stream

        stream = async_pipe(items)
        assert isinstance(stream, AsyncIterator)
        assert not isawaitable(stream)
        assert await anext(stream) == {"content": "a"}

    @async_test
    async def test_legacy_coroutine_parser_operator_returns_async_iterator(self):
        items = [{"content": "a"}, {"content": "b"}]

        @operator(isasync=True)
        async def async_pipe(stream, objconf, tuples, **kwargs):
            return iter(items)

        stream = async_pipe(items)
        assert isinstance(stream, AsyncIterator)
        assert not isawaitable(stream)
        assert [item async for item in stream] == items


ENUM_MEMBER_NAMES = [
    pytest.param("fetch-page", None, "FETCH_PAGE", id="dash"),
    pytest.param("ms.autopilot.ensure", None, "MS_AUTOPILOT_ENSURE", id="dotted"),
    pytest.param("a--b..c", None, "A_B_C", id="repeated-separators"),
    pytest.param("fetch", "grab", "GRAB", id="override"),
]


class TestEnumMemberName:
    @pytest.mark.parametrize(("name", "override", "expected"), ENUM_MEMBER_NAMES)
    def test_enum_member_name(self, name, override, expected):
        assert enum_member_name(name, override=override) == expected


MEMBER_COLLISIONS = (
    pytest.param("my_mod", "my-mod", id="builtin"),
    pytest.param("example.my_mod", "example.my-mod", id="provider"),
)


def _exec_generated_names(*entries: NameEntry) -> dict:
    namespace: dict = {}
    exec(generate_module_names(*entries), namespace)
    return namespace


class TestGenerateModuleNames:
    def test_generation_is_order_independent(self):
        entries = list(gen_catalog_entries())
        assert generate_module_names(*entries) == generate_module_names(
            *reversed(entries)
        )

    def test_enum_name_override_resolves_collision(self):
        entries = [
            NameEntry(name="my_mod", category="transform"),
            NameEntry(name="my-mod", category="transform", enum_name="my_mod_alt"),
        ]
        transforms = _exec_generated_names(*entries)["Transforms"]

        assert transforms.MY_MOD_ALT.value == "my-mod"
        assert transforms.MY_MOD.value == "my_mod"

    def test_provider_namespace_flattens(self):
        builtin = NameEntry(name="fetch", category="source")
        entry = NameEntry(name="microsoft.autopilot.ensure", category="transform")
        namespace = _exec_generated_names(builtin, entry)
        provider = namespace["Microsoft"]
        modules = namespace["Modules"]

        assert entry.provider == "microsoft"
        assert entry.class_name == "Microsoft"
        assert entry.member == "AUTOPILOT_ENSURE"
        assert entry.alias == "MICROSOFT_AUTOPILOT_ENSURE"
        assert provider.AUTOPILOT_ENSURE.value == "microsoft.autopilot.ensure"
        assert modules.MICROSOFT_AUTOPILOT_ENSURE is provider.AUTOPILOT_ENSURE
        assert "AUTOPILOT_ENSURE" not in namespace["Transforms"].__members__

    @pytest.mark.parametrize(("first", "second"), MEMBER_COLLISIONS)
    def test_member_collision_fails_with_diagnostic(self, first, second):
        entries = [
            NameEntry(name=first, category="transform"),
            NameEntry(name=second, category="transform"),
        ]

        with pytest.raises(ValueError, match="enum_name") as excinfo:
            generate_module_names(*entries)

        assert repr(first) in str(excinfo.value)
        assert repr(second) in str(excinfo.value)
