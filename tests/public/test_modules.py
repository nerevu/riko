# vim: sw=4:ts=4:expandtab
"""Provides public tests for built-in modules, module discovery, and import surfaces."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from importlib import import_module
from importlib.resources import files
from itertools import count
from time import struct_time
from types import BuiltinFunctionType, FunctionType, SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

import riko
import riko.bado
import riko.base.exceptions
import riko.definitions._workflow_definition
import riko.ext
import riko.ext.codegen
import riko.ext.modules
import riko.ext.targets
import riko.ext.workflows
import riko.modules
import riko.modules._names
import riko.runtime._compile
import riko.runtime._export
import riko.runtime._resolver
import riko.runtime._workflow_pipes
import riko.runtime._workflow_resolver
import riko.runtime._workflow_stores
import riko.types
from riko.bado._backend import create_task_group
from riko.base._api_surface import (
    BADO,
    COMPILE,
    EXPORT,
    EXT_CODEGEN,
    EXT_MODULES,
    EXT_TARGETS,
    EXT_WORKFLOWS,
    EXTENSION,
    MODULES,
    PRIVATE_RESOLUTION,
    ROOT_EXCEPTIONS,
    STABLE,
    TYPES,
)
from riko.base._exceptions import ReceiverUnavailableError
from riko.coercion import cast as cast_module
from riko.definitions._context import Context
from riko.modules import describe_module
from riko.modules._metadata import list_modules
from riko.modules.aggregate import pipe as aggregate_pipe
from riko.modules.fetchdata import async_pipe as async_fetchdata_pipe
from riko.modules.fetchdata import pipe as fetchdata_pipe
from riko.modules.filter import pipe as filter_pipe
from riko.modules.input import pipe as input_pipe
from riko.modules.join import pipe as join_pipe
from riko.modules.receive import pipe as receive_pipe
from riko.modules.send import async_pipe as async_send
from riko.modules.send import pipe as send_pipe
from riko.modules.slugify import pipe as slugify_pipe
from riko.modules.sort import pipe as sort_pipe
from riko.modules.udf import pipe as udf_pipe
from riko.runtime._pubsub import async_hub
from riko.types._enums import CastType, SortableCastType
from riko.types.modules import (
    FilterConf,
    FilterConfRule,
    InputConf,
    JoinConf,
    SendConf,
    SortConf,
    SortConfRule,
)
from tests import async_test

if TYPE_CHECKING:
    from riko.types._streams import AsyncStream, Item, ItemOrValue, Stream


_LOOKAHEAD = 2
_SOURCE_LEN = 5


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


URL = "https://example.test/data"
JSON = b'{"items": [{"title": "A"}, {"title": "B"}]}'
XML = b"<root><items><title>A</title></items><items><title>B</title></items></root>"


def _async_get(content, content_type):
    async def async_get(url, **_):
        return SimpleNamespace(content=content, headers={"content-type": content_type})

    return async_get


async def _titles(conf):
    stream = async_fetchdata_pipe(conf=conf)
    return [item.get("title") async for item in stream]


class TestFetchdata:
    """``fetchdata`` infers the parser for extensionless URLs and local documents."""

    @pytest.mark.parametrize(
        ("content", "content_type"), [(JSON, "application/json"), (XML, "text/xml")]
    )
    @async_test
    async def test_file_contents(self, monkeypatch, content, content_type):
        monkeypatch.setattr(
            "riko.io._async.async_get", _async_get(content, content_type)
        )
        result = await _titles({"url": URL, "path": "items"})
        assert result == ["A", "B"]

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
    @async_test
    async def test_query_string_does_not_defeat_extension(self, monkeypatch):
        """Detect URL formats from extensions even when queries are present."""
        monkeypatch.setattr(
            "riko.io._async.async_get", _async_get(JSON, "application/json")
        )
        url = "https://example.test/export.json?token=abc"
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


class TestFilter:
    def test_filter_greater_less_compare_numeric_strings_numerically(self):
        """
        Compare numeric operands numerically and other operands lexically.

        Numeric strings such as ``"10"`` and ``"9"`` use numeric ordering; non-numeric
        strings use lexicographic ordering.
        """
        numeric_strings = [{"x": "9"}, {"x": "10"}]
        string_rule = FilterConfRule(field="x", op="greater", value="9")
        conf = FilterConf({"rule": string_rule})
        assert _values(filter_pipe(numeric_strings, conf=conf), "x") == ["10"]

        numbers = [{"x": 9}, {"x": 10}]
        numeric_rule = FilterConfRule(field="x", op="greater", value=9)
        conf = FilterConf({"rule": numeric_rule})
        assert _values(filter_pipe(numbers, conf=conf), "x") == [10]

        words = [{"x": "apple"}, {"x": "banana"}]
        word_rule = FilterConfRule(field="x", op="greater", value="apple")
        conf = FilterConf({"rule": word_rule})
        assert _values(filter_pipe(words, conf=conf), "x") == ["banana"]

    def test_filter_ordered_coercion_is_all_or_nothing(self):
        """
        Fall back to lexical comparison when numeric coercion is incomplete.

        Mixed numeric/text pairs avoid ``Decimal``-versus-``str`` errors. Non-finite
        values such as ``inf`` and ``nan`` are also compared as strings.
        """
        mixed = [{"x": "10"}, {"x": "apple"}]
        conf = FilterConf(
            {"rule": FilterConfRule(field="x", op="greater", value="banana")}
        )
        assert _values(filter_pipe(mixed, conf=conf), "x") == []

        nonfinite = [{"x": "nan"}, {"x": "5"}]
        conf = FilterConf({"rule": FilterConfRule(field="x", op="greater", value="9")})
        assert _values(filter_pipe(nonfinite, conf=conf), "x") == ["nan"]

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

        assert _values(filter_pipe(items, conf=conf), "x") == []

        monkeypatch.setattr("riko.modules.filter.ALLOW_INF", True)
        assert _values(filter_pipe(items, conf=conf), "x") == ["-inf"]

        nan_items = [{"x": "nan"}]
        nan_conf = FilterConf(
            {"rule": FilterConfRule(field="x", op="greater", value="9")}
        )
        assert _values(filter_pipe(nan_items, conf=nan_conf), "x") == ["nan"]


def _counting_source(consumed: list[int]) -> Any:
    for i in count():
        consumed.append(i)
        yield {"x": "foo", "i": i}


SLUGIFY_CASES = [
    pytest.param("北京 市", "bei-jing-shi", id="han-transliteration"),
    pytest.param("ß straße", "ss-strasse", id="eszett-expansion"),
]


class TestSlugify:
    @pytest.mark.parametrize(("content", "slug"), SLUGIFY_CASES)
    def test_non_ascii_content_transliterates(self, content, slug):
        assert _values(slugify_pipe({"content": content}), "slugify") == [slug]


class TestJoin:
    def test_keyed_join_does_not_materialize_its_primary(self):
        """``other`` is the replayed side, so an unbounded primary must still emit."""
        consumed: list[int] = []
        other = [{"x": "bar", "c": 4}, {"x": "foo", "c": 5}]
        conf = JoinConf(join_key="x")
        joined = join_pipe(_counting_source(consumed), conf=conf, other=other)

        assert next(joined) == {"x": "foo", "i": 0, "c": 5}
        assert len(consumed) <= _LOOKAHEAD
        assert next(joined) == {"x": "foo", "i": 1, "c": 5}
        assert len(consumed) <= 1 + _LOOKAHEAD

    def test_natural_join_does_not_materialize_its_primary(self):
        """The keyless natural join is lazy in its primary stream too."""
        consumed: list[int] = []
        joined = join_pipe(_counting_source(consumed), other=[{"c": 5}])

        assert next(joined) == {"x": "foo", "i": 0, "c": 5}
        assert len(consumed) <= _LOOKAHEAD


class TestSort:
    @pytest.mark.parametrize(
        ("dir_", "type_", "vals"),
        [
            ("asc", SortableCastType.FLOAT, ["1", "2", "3"]),
            ("asc", SortableCastType.DECIMAL, ["1", "2", "3"]),
            ("asc", SortableCastType.DATE, ["2019-01-01", "2020-05-01", "2024-11-12"]),
            (
                "asc",
                SortableCastType.DATETIME,
                ["2019-01-01", "2020-05-01", "2024-11-12"],
            ),
            ("desc", SortableCastType.FLOAT, ["1", "2", "3"]),
            ("desc", SortableCastType.DECIMAL, ["1", "2", "3"]),
            ("desc", SortableCastType.DATE, ["2019-01-01", "2020-05-01", "2024-11-12"]),
            (
                "desc",
                SortableCastType.DATETIME,
                ["2019-01-01", "2020-05-01", "2024-11-12"],
            ),
        ],
    )
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


def _finite_source(consumed: list[int]) -> Stream:
    for i in range(_SOURCE_LEN):
        consumed.append(i)
        yield {"x": "foo", "i": i}


async def _afinite_source(consumed: list[int]) -> AsyncStream:
    for i in range(_SOURCE_LEN):
        consumed.append(i)
        yield {"x": "foo", "i": i}


async def _drain(receive_stream: Any, into: list[Item] | None = None) -> None:
    async for item in receive_stream:
        if into is not None:
            into.append(item)


async def _send_first(consumed: list[int]) -> tuple[ItemOrValue, int]:
    first: ItemOrValue = {}
    seen = 0

    async with (
        async_hub.subscribe("r4-lazy") as receive_stream,
        create_task_group() as tg,
    ):
        tg.start_soon(_drain, receive_stream)
        stream = async_send(_finite_source(consumed), others=["r4-lazy"])
        first = await anext(stream)
        seen = len(consumed)

    return (first, seen)


async def _send_missing_target(received: list[Item]) -> None:
    async with (
        async_hub.subscribe("r4-good") as receive_stream,
        create_task_group() as tg,
    ):
        tg.start_soon(_drain, receive_stream, received)

        with pytest.raises(ReceiverUnavailableError):
            async for _ in async_send(
                _finite_source([]),
                conf=SendConf(max_wait=0.05),
                others=["r4-good", "r4-missing"],
            ):
                pass


async def _send_feed(consumed: list[int], received: list[Item]) -> list[ItemOrValue]:
    out: list[ItemOrValue] = []

    async with (
        async_hub.subscribe("r4-feed") as receive_stream,
        create_task_group() as tg,
    ):
        tg.start_soon(_drain, receive_stream, received)
        stream = async_send(_afinite_source(consumed), others=["r4-feed"])
        out = [item async for item in stream]

    return out


class TestAsyncSend:
    @pytest.mark.timeout(10)
    @pytest.mark.xfail(reason="lazy async fan-out is not yet implemented", strict=True)
    @async_test
    async def test_async_send_does_not_buffer_its_source(self):
        """Keep unbounded async sends from returning before completion."""
        consumed: list[int] = []
        first, seen = await _send_first(consumed)

        assert first == {"x": "foo", "i": 0}
        assert seen <= _LOOKAHEAD

    @pytest.mark.timeout(10)
    @async_test
    async def test_async_send_completes_targets_when_publish_fails(self):
        """
        A failed publish must still close the targets that did subscribe.

        ``publish`` raises ``ReceiverUnavailableError`` once an unsubscribed target
        outlasts ``max_wait``.
        """
        received: list[Item] = []
        await _send_missing_target(received)
        assert received == [{"x": "foo", "i": 0}]

    @pytest.mark.timeout(10)
    @async_test
    async def test_async_send_accepts_a_feed_source(self):
        """
        An async source reaches the parser as an ``AsyncIterator``, not a list.

        ``operator.anormalize_input``/``setup`` hand the parser an async ``orig_stream``
        when the caller passes a ``Feed``. So a sync ``for`` over it raises
        ``TypeError``.
        """
        consumed: list[int] = []
        received: list[Item] = []
        expected = [{"x": "foo", "i": i} for i in range(_SOURCE_LEN)]
        out = await _send_feed(consumed, received)

        assert out == expected
        assert received == expected


async def _receive_first(consumed: list[int]) -> tuple[ItemOrValue, int]:
    first: ItemOrValue = {}
    seen = 0

    async def _snapshot(receive_stream: Any) -> None:
        nonlocal first, seen
        idx = 0

        async for item in receive_stream:
            if idx == 0:
                first, seen = item, len(consumed)

            idx += 1

    async with (
        async_hub.subscribe("r-recv-lazy") as receive_stream,
        create_task_group() as tg,
    ):
        tg.start_soon(_snapshot, receive_stream)
        async for _ in async_send(_finite_source(consumed), others=["r-recv-lazy"]):
            pass

    return (first, seen)


class TestAsyncReceive:
    @pytest.mark.timeout(10)
    @async_test
    async def test_async_receive_does_not_materialize(self):
        """
        Deliver each item before pulling the next one from the source.

        The zero-buffer channel lets subscribers observe items without materializing
        the source. ``send`` still eagerly collects its own passthrough return; see
        ``test_async_send_does_not_buffer_its_source``.
        """
        consumed: list[int] = []
        first, seen = await _receive_first(consumed)

        assert first == {"x": "foo", "i": 0}
        assert seen <= _LOOKAHEAD


_OMITTED = object()


class TestRequiredOperands:
    @pytest.mark.parametrize(
        ("pipe", "operand", "value"),
        [
            pytest.param(udf_pipe, "func", _OMITTED, id="udf-omitted"),
            pytest.param(aggregate_pipe, "func", _OMITTED, id="aggregate-omitted"),
            pytest.param(join_pipe, "other", _OMITTED, id="join-omitted"),
            pytest.param(send_pipe, "others", _OMITTED, id="send-omitted"),
            pytest.param(udf_pipe, "func", 0, id="udf-empty"),
            pytest.param(aggregate_pipe, "func", 0, id="aggregate-empty"),
            pytest.param(join_pipe, "other", [], id="join-empty"),
            pytest.param(send_pipe, "others", [], id="send-empty"),
        ],
    )
    def test_missing_operand_raises(self, pipe: Any, operand: str, value: object):
        """An omitted or empty operand is a call-site error that names the operand."""
        kwargs = {} if value is _OMITTED else {operand: value}

        with pytest.raises(TypeError, match=f"requires the {operand!r} keyword"):
            list(pipe([{"x": 0}], **kwargs))


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

    @pytest.mark.parametrize(
        ("kind", "subtype"),
        [
            pytest.param(None, "source", id="sources"),
            pytest.param("processor", None, id="processors"),
        ],
    )
    def test_filter_non_loopable_by_kind(self, kind: str | None, subtype: str | None):
        modules = list_modules(type=kind, subtype=subtype, loopable=False)
        assert modules == ["input"]

    def test_type_and_subtype_cannot_be_combined(self):
        with pytest.raises(ValueError, match="type and subtype cannot be combined"):
            list_modules(type="operator", subtype="composer")

    def test_primary_requires_subtype(self):
        with pytest.raises(ValueError, match="primary=True requires subtype"):
            list_modules(primary=True)


class TestDescribeModule:
    @pytest.mark.parametrize(
        ("error", "match"),
        [
            pytest.param(
                ModuleNotFoundError(
                    "No module named 'phantom_dep'", name="phantom_dep"
                ),
                "phantom_dep",
                id="nested-dependency",
            ),
            pytest.param(
                ModuleNotFoundError("broken import with no module name"),
                "no module name",
                id="unnamed",
            ),
        ],
    )
    def test_describe_module_reraises_import_error(
        self, monkeypatch, error: ModuleNotFoundError, match: str
    ):
        def boom(target):
            raise error

        monkeypatch.setattr("riko.base._typing.import_module", boom)

        with pytest.raises(ModuleNotFoundError, match=match):
            describe_module("hash")


SURFACE_MODULES = (
    riko.bado,
    riko.runtime._export,
    riko.runtime._compile,
    riko.definitions._workflow_definition,
    riko.ext,
    riko.modules,
    riko.base.exceptions,
    riko,
    riko.types,
)
PARTIAL_SURFACES = (
    (riko.modules.__all__ + riko.modules._names.__all__, MODULES),
    (riko.base.exceptions.__all__, ROOT_EXCEPTIONS),
)
CONF_TYPES = riko.types.modules.__all__


CODEGEN = (COMPILE & {"compile_workflow"}) | {"RAW_CONFS", "render_value"}

EQUAL_SURFACES = (
    (riko.bado, BADO),
    (riko.runtime._export, EXPORT),
    (riko.runtime._compile, CODEGEN),
    (
        riko.definitions._workflow_definition,
        {"Workflow", "migrate_v1_to_v2", "normalize_workflow"},
    ),
    (riko.ext, EXTENSION),
    (riko.ext.codegen, EXT_CODEGEN),
    (riko.ext.modules, EXT_MODULES),
    (riko.ext.targets, EXT_TARGETS),
    (riko.ext.workflows, EXT_WORKFLOWS),
    (riko, STABLE),
    (riko.types, TYPES),
)
PUBLIC_EXTENSION_MODULES = (
    "riko.ext.codegen",
    "riko.ext.modules",
    "riko.ext.targets",
    "riko.ext.workflows",
)
REMOVED_PUBLIC_PATHS = tuple(
    f"riko.ext.{name}" for name in ("config", "decorators", "protocols", "registry")
)
RESOLUTION_MODULES = (
    riko.runtime._resolver,
    riko.runtime._workflow_pipes,
    riko.runtime._workflow_stores,
    riko.runtime._workflow_resolver,
)


def id_func(val):
    if hasattr(val, "__name__"):
        return val.__name__
    else:
        return "vs-set"


def _gen_subclasses(cls):
    for subclass in cls.__subclasses__():
        yield subclass
        yield from _gen_subclasses(subclass)


class TestImportSurface:
    """
    Check the public API boundary.

    ``riko`` define the stable application API. ``riko.ext`` defines the
    extension-author API. ``riko.bado`` is a supported async-runtime namespace; the
    BADO subset is promoted into the stable application surface. These tests exercise
    public imports rather than implementation details.
    """

    @pytest.mark.smoke
    def test_package_ships_py_typed(self):
        assert files("riko").joinpath("py.typed").is_file()

    @pytest.mark.smoke
    @pytest.mark.parametrize(("module", "surface"), EQUAL_SURFACES, ids=id_func)
    def test_equal_surface_matches_expected(self, module, surface):
        assert sorted(set(module.__all__)) == sorted(surface)

    @pytest.mark.parametrize(("names", "surface"), PARTIAL_SURFACES, ids=id_func)
    def test_partial_surface_matches_expected(self, names, surface):
        assert surface.issubset(names)
        assert not any(name.startswith("_") for name in names)

    def test_normal_module_confs_are_public(self):
        assert "FetchConf" in CONF_TYPES
        assert "RegexConf" in CONF_TYPES
        assert "ItemBuilderConf" in CONF_TYPES

    def test_raw_module_confs_are_private(self):
        leaked = sorted(
            name for name in CONF_TYPES if name.endswith(("RawConf", "RawRule"))
        )
        assert not leaked, f"Raw module confs leaked into riko.types.modules: {leaked}"

    def test_module_metadas_are_same(self):
        assert riko.ext.ModuleMetadata is riko.types.modules.ModuleMetadata

    @pytest.mark.parametrize(
        ("module", "surface"), [(riko, STABLE), (riko.ext, EXTENSION)]
    )
    def test_stable_names_importable(self, module, surface):
        """Every declared stable names actually resolves on ``riko``."""
        assert all(hasattr(module, name) for name in surface)

    def test_bado_reexports_are_same_object(self):
        mismatches = sorted(
            name
            for name in riko.bado.__all__
            if getattr(riko, name) is not getattr(riko.bado, name)
        )
        assert not mismatches, f"Bado reexports differ from riko: {mismatches}"

    def test_exception_reexports_are_same_object(self):
        mismatches = sorted(
            name
            for name in ROOT_EXCEPTIONS
            if getattr(riko, name) is not getattr(riko.base.exceptions, name)
        )
        assert not mismatches, f"Exception reexports differ from riko: {mismatches}"

    def test_exceptions_naming_the_public_module_are_importable_from_it(self):
        public = riko.base.exceptions
        roots = (public.RikoError, public.RikoWarning)
        unexported = sorted(
            cls.__name__
            for root in roots
            for cls in (root, *_gen_subclasses(root))
            if cls.__module__ == public.__name__ and cls.__name__ not in public.__all__
        )
        assert not unexported, f"Not importable from {public.__name__}: {unexported}"

    def test_private_resolution_names_exist(self):
        """Every declared private resolution name is defined by a resolution module."""
        missing = sorted(
            name
            for name in PRIVATE_RESOLUTION
            if not any(hasattr(module, name) for module in RESOLUTION_MODULES)
        )
        assert not missing, f"Declared resolution internals do not exist: {missing}"

    @pytest.mark.parametrize(
        "module",
        [*SURFACE_MODULES, *map(import_module, PUBLIC_EXTENSION_MODULES)],
        ids=lambda module: module.__name__,
    )
    def test_no_accidental_internal_exports(self, module):
        """Private resolution internals are neither exported nor reachable publicly."""
        exported = PRIVATE_RESOLUTION.intersection(getattr(module, "__all__", ()))
        reachable = {name for name in PRIVATE_RESOLUTION if hasattr(module, name)}
        leaked = sorted(exported | reachable)
        assert not leaked, f"Private resolution internals exposed: {leaked}"

    @pytest.mark.parametrize("module", RESOLUTION_MODULES, ids=lambda m: m.__name__)
    def test_resolution_internals_have_no_public_path(self, module):
        """Resolution internals live only behind ``_``-prefixed modules."""
        package, _, private_name = module.__name__.rpartition(".")
        public_path = f"{package}.{private_name.lstrip('_')}"
        assert private_name.startswith("_")

        with pytest.raises(ModuleNotFoundError):
            import_module(public_path)

    def test_no_leaked_public_functions(self):
        """
        No bare function leaks into the top-level namespace outside ``__all__``.

        Scoped to *functions* on purpose: classes and constants (e.g. ``Context``,
        ``ENCODING``, ``objectify``) are intentionally importable while absent from
        ``__all__``, so this guards callables rather than the whole attribute surface
        (that surface is pinned by ``test_equal_surface_matches_expected``).
        """
        leaked = sorted(
            name
            for name, val in vars(riko).items()
            if not (name.startswith("_") or name in STABLE)
            and isinstance(val, (FunctionType, BuiltinFunctionType))
        )
        assert not leaked, f"Top-level functions leaked outside STABLE: {leaked}"

    @pytest.mark.parametrize("path", REMOVED_PUBLIC_PATHS)
    def test_removed_public_paths_are_gone(self, path):
        with pytest.raises(ModuleNotFoundError):
            import_module(path)

    def test_modules_package_drops_decorators(self):
        names = ("operator", "processor", "splitter")
        assert not any(hasattr(riko.modules, name) for name in names)

    def test_stable_and_extension_do_not_intersect(self):
        common = STABLE & EXTENSION
        assert not common, f"Stable and extension surfaces intersect: {common}"

    def test_all_has_no_duplicates(self):
        duplicates = {
            module.__name__: sorted(
                {name for name in module.__all__ if module.__all__.count(name) > 1}
            )
            for module in SURFACE_MODULES
            if len(module.__all__) != len(set(module.__all__))
        }
        assert not duplicates, f"Duplicate __all__ entries: {duplicates}"
