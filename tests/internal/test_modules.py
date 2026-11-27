# vim: sw=4:ts=4:expandtab
"""Provides internal tests for module decorators, metadata, loops, and resolvers."""

from __future__ import annotations

import asyncio
import itertools
from collections.abc import (
    AsyncGenerator,
    AsyncIterable,
    AsyncIterator,
    Awaitable,
    Generator,
    Iterator,
)
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from functools import wraps
from inspect import Parameter, isawaitable, iscoroutinefunction, signature
from json import loads
from time import monotonic
from types import ModuleType, SimpleNamespace
from typing import TYPE_CHECKING, Annotated, Any, Literal, assert_type, cast

import attrs
import pytest

from riko.bado._backend import Event, async_sleep, create_task_group, fail_after
from riko.bado._util import maybe_aclosing, maybe_closing
from riko.bado.itertools import AsyncTeeBranch, as_async
from riko.base import _paths as paths_module
from riko.base._exceptions import InvalidPipelineError, ReceiverUnavailableError
from riko.base._iterutils import auto_close
from riko.base._paths import PACKAGE_DIR, get_path
from riko.base._sentinels import MISSING
from riko.coercion import cast as cast_module
from riko.coercion._configs import CsvObjconf, ExchangeRateObjconf
from riko.coercion._objectify import objectify
from riko.definitions._context import Context
from riko.definitions._wrapping import stamp_wrapper_meta
from riko.execution._resource_view import ResourceView
from riko.modules import _inference, _metadata, csv, fetchtable
from riko.modules import count as count_module
from riko.modules import exchangerate as exchangerate_module
from riko.modules import filter as filter_module
from riko.modules import truncate as truncate_module
from riko.modules import uniq as uniq_module
from riko.modules._assignment import gen_assignments
from riko.modules._decorators import operator, processor, splitter
from riko.modules._inference import (
    gen_operator_return_kinds,
    gen_return_inferences,
    infer_return_kinds,
)
from riko.modules._metadata import get_module_metadata
from riko.modules._prepare import build_conf, resolve_and_cast
from riko.modules.fetchpage import get_string
from riko.modules.filter import pipe as filter_pipe
from riko.modules.join import pipe as join
from riko.modules.loop import async_pipe as async_loop
from riko.modules.loop import pipe as loop
from riko.modules.send import async_pipe as async_send
from riko.modules.split import async_pipe as async_split
from riko.modules.split import pipe as split
from riko.modules.strconcat import pipe as strconcat
from riko.modules.timeout import AsyncTimeoutIterator
from riko.modules.tokenizer import async_pipe as async_tok
from riko.modules.tokenizer import pipe as tokenizer
from riko.modules.truncate import async_pipe as async_truncate
from riko.modules.union import async_pipe as async_union
from riko.modules.union import pipe as union
from riko.parsing._dotdict import DotDict
from riko.runtime._pubsub import async_hub
from riko.runtime._workflow_pipes import workflow
from riko.types._options import ItemDispatch, ValueDispatch
from riko.types._wrappers import (
    PARSER_POSITIONALS,
    WRAPPER_META,
    AsyncProcessorWrapper,
    AsyncSplitterWrapper,
    AsyncSubPipe,
    AwaitableOperatorParser,
    AwaitableProcessorParser,
    AwaitableSplitterParser,
    DeclaresIdentity,
    SyncOperatorParser,
    SyncProcessorParser,
    SyncProcessorWrapper,
    SyncSplitterParser,
    require_async_wrapper,
    require_sync_wrapper,
)
from riko.types.modules import (
    Conf,
    CsvConf,
    FilterConf,
    FilterConfRule,
    InferenceSource,
    OperatorReturnKind,
    SendConf,
    StrconcatRawConf,
)
from tests import ROUND_TRIPS, async_test, pickle_round_trip, skipif_sync
from tests._lifecycle import (
    LOOKAHEAD,
    PARENTS,
    TOKENIZER_CONF,
    build_async_lazy_embed,
    build_lazy_embed,
    gen_lazy_child,
)
from tests._resources import Connection
from tests._streams import AsyncPullLog, Closable, PullLog, gen_items

if TYPE_CHECKING:
    from riko.coercion._dynamic_conf import DynamicConf
    from riko.types._streams import (
        AsyncCascade,
        AsyncStream,
        Cascade,
        Feed,
        Item,
        ItemOrValue,
        Stream,
    )
    from riko.types._wrappers import (
        PipeTuples,
        SyncModuleWrapper,
        SyncOperatorWrapperOutput,
    )

type _AliasStream = Iterator[int]
type _UnavailableAlias = DynamicConf | int


def _sync_subpipe(item: Item, context: Context | None = None, **_) -> Stream:
    title = str(item.get("title", ""))
    return iter([{"content": title.upper()}, {"content": title[::-1]}])


_SYNC_SUBPIPE = workflow()(_sync_subpipe)


async def _async_subpipe(item: Item, context: Context | None = None, **_) -> Stream:
    title = str(item.get("title", ""))
    return iter([{"content": title.upper()}, {"content": title[::-1]}])


_ASYNC_SUBPIPE = workflow()(_async_subpipe)
_SOURCE_LEN = 5
_SOURCE_ROWS = [{"x": "foo", "i": i} for i in range(_SOURCE_LEN)]
_LONG_ROWS = [{"i": i} for i in range(10_000)]
_PLACES = Decimal("0.0001")
BARE_ROWS = [{"content": "hi"}]
DECORATORS = [processor, operator, splitter]
FIXED_ROWS = [{"x": 1}]
FIXED_SPLITTER = splitter(objectify=False)
FIXED_CONTEXT = {"context": Context()}
STREAM = OperatorReturnKind.STREAM
NONSTREAM = OperatorReturnKind.NONSTREAM
UNKNOWN = OperatorReturnKind.UNKNOWN
GENERATOR = InferenceSource.GENERATOR
ANNOTATION = InferenceSource.ANNOTATION
AST = InferenceSource.AST
SUBPIPE_PARENTS = [{"title": "ab"}, {"title": "cd"}]


def shout(item: Item, *args, **kwargs) -> str:
    return str(item.get("content", "")).upper()


async def _async_shout(item: Item, *args, **kwargs) -> str:
    return shout(item)


def _count(stream: Stream, *args, **kwargs) -> int:
    return sum(1 for _ in stream)


async def _async_count(stream: Stream, *args, **kwargs) -> int:
    return _count(stream)


def _twice(stream: Stream, *args, **kwargs) -> Cascade:
    items = list(stream)
    return iter([iter(items), iter(items)])


async def _async_twice(stream: Stream, *args, **kwargs) -> Cascade:
    return _twice(stream)


async def _drain(value: object) -> object:
    _value = await value if isawaitable(value) else value

    if isinstance(_value, AsyncIterable):
        result = [await _drain(part) async for part in _value]
    elif isinstance(_value, Iterator):
        result = [await _drain(part) for part in _value]
    else:
        result = _value

    return result


BARE_FORMS = [
    pytest.param(processor, shout, {"assign": "content"}, id="processor-sync"),
    pytest.param(processor, _async_shout, {"assign": "content"}, id="processor-async"),
    pytest.param(operator, _count, {}, id="operator-sync"),
    pytest.param(operator, _async_count, {}, id="operator-async"),
    pytest.param(splitter, _twice, {}, id="splitter-sync"),
    pytest.param(splitter, _async_twice, {}, id="splitter-async"),
]
BARE_AND_OPTIONS = [
    pytest.param(processor, (), {"is_async": True}, id="processor+is_async"),
    pytest.param(operator, ({},), {}, id="operator+defaults"),
    pytest.param(splitter, (), {"objectify": False}, id="splitter+objectify"),
]


class TestBareDecorator:
    """A decorator applied without being called first."""

    @pytest.mark.parametrize(("decorator", "parser", "kwargs"), BARE_FORMS)
    def test_bare_stamps_called_metadata(self, decorator, parser, kwargs) -> None:
        bare, called = decorator(parser), decorator()(parser)
        assert [getattr(bare, attr) for attr in WRAPPER_META] == [
            getattr(called, attr) for attr in WRAPPER_META
        ]

    @async_test
    @pytest.mark.parametrize(("decorator", "parser", "kwargs"), BARE_FORMS)
    async def test_bare_output_matches_called(self, decorator, parser, kwargs) -> None:
        bare = await _drain(decorator(parser)(BARE_ROWS, **kwargs))
        assert bare == await _drain(decorator()(parser)(BARE_ROWS, **kwargs))

    def test_bare_and_called_forms_type_check(self) -> None:
        assert_type(processor(shout), SyncProcessorWrapper)
        assert_type(processor(), processor[Literal[False]])

    @pytest.mark.parametrize("round_trip", ROUND_TRIPS)
    @pytest.mark.parametrize("decorator", DECORATORS)
    def test_default_instance_round_trips(self, decorator, round_trip) -> None:
        assert type(round_trip(decorator())) is decorator

    @pytest.mark.parametrize(("decorator", "args", "kwargs"), BARE_AND_OPTIONS)
    def test_function_with_options_raises(self, decorator, args, kwargs) -> None:
        with pytest.raises(TypeError, match="either the function to wrap or"):
            decorator(shout, *args, **kwargs)


def _fixed_processor(item: Item, extraction: object, objconf: object) -> str:
    return shout(item)


def _fixed_operator(stream: Stream, extraction: object, tuples: object) -> int:
    return _count(stream)


def _fixed_splitter(stream: Stream, extraction: object, tuples: object) -> Cascade:
    return iter([stream])


FIXED_ARITY = [
    pytest.param(processor(), _fixed_processor, {"content": "hi"}, {}, id="processor"),
    pytest.param(operator(), _fixed_operator, FIXED_ROWS, {}, id="operator"),
    pytest.param(
        FIXED_SPLITTER, _fixed_splitter, FIXED_ROWS, FIXED_CONTEXT, id="splitter"
    ),
]
PARSER_PROTOCOLS = [
    pytest.param(SyncProcessorParser, id="sync-processor"),
    pytest.param(SyncOperatorParser, id="sync-operator"),
    pytest.param(SyncSplitterParser, id="sync-splitter"),
    pytest.param(AwaitableProcessorParser, id="awaitable-processor"),
    pytest.param(AwaitableOperatorParser, id="awaitable-operator"),
    pytest.param(AwaitableSplitterParser, id="awaitable-splitter"),
]


class TestParserSignature:
    """
    The ``**kwargs`` a parser needs for the keyword arguments its decorator passes.

    A parser without ``**kwargs`` is rejected by the type checker at decoration,
    since the call would otherwise fail with ``TypeError`` on the first item.
    """

    def test_processor_parser_with_kwargs_is_accepted(self) -> None:
        def parser(item: Item, extraction: object, objconf: object, **_: object) -> str:
            return shout(item)

        pipe = processor()(parser)
        assert next(pipe({"content": "hi"}, assign="content")) == {"content": "HI"}

    @pytest.mark.parametrize("protocol", PARSER_PROTOCOLS)
    def test_parser_protocol_takes_the_positional_count(self, protocol) -> None:
        _, *params = signature(protocol.__call__).parameters.values()
        kinds = [p.kind for p in params]
        assert kinds.count(Parameter.POSITIONAL_ONLY) == PARSER_POSITIONALS

    def test_fixed_arity_parser_is_a_type_error(self) -> None:
        pipes = [
            processor()(_fixed_processor),  # pyright: ignore[reportArgumentType, reportCallIssue]
            operator()(_fixed_operator),  # pyright: ignore[reportArgumentType, reportCallIssue]
            FIXED_SPLITTER(_fixed_splitter),  # pyright: ignore[reportArgumentType, reportCallIssue]
        ]
        assert all(map(callable, pipes))

    @pytest.mark.parametrize(("decorate", "parser", "source", "kwargs"), FIXED_ARITY)
    def test_fixed_arity_parser_fails_at_first_call(
        self, decorate, parser, source, kwargs
    ) -> None:
        pipe = decorate(parser)

        with pytest.raises(TypeError, match="unexpected keyword argument"):
            next(pipe(source, **kwargs))


class _FalsyRows:
    """An iterable of rows whose truth value is ``False``."""

    def __iter__(self) -> Stream:
        return iter(FIXED_ROWS)

    def __bool__(self) -> bool:
        return False


class TestNormalizeInput:
    @pytest.mark.parametrize("decorator", [operator, splitter])
    def test_reads_a_falsy_iterable(self, decorator) -> None:
        assert list(decorator().normalize_input(_FalsyRows())) == FIXED_ROWS

    def test_processor_normalizes_a_none_input_to_an_empty_item(self):
        assert processor().normalize_input(None) == {}

    def test_operator_wraps_a_none_item_as_content(self):
        items = cast("Any", [None])
        assert next(operator().normalize_input(items)) == {"content": None}

    def test_operator_yields_the_dotdicts_it_received(self) -> None:
        items = [DotDict({"x": 1}), DotDict({"x": 2})]
        results = list(union(items))
        assert list(map(id, results)) == list(map(id, items))

    @async_test
    async def test_async_operator_yields_the_dotdicts_it_received(self) -> None:
        items = [DotDict({"x": 1}), DotDict({"x": 2})]
        stream = async_truncate(as_async(items), conf={"count": 5})
        results = [item async for item in stream]
        assert list(map(id, results)) == list(map(id, items))


class TestSplitter:
    """The splitter wrapper over async input and context."""

    def test_a_splitter_call_declares_no_identity(self) -> None:
        prepared = split.prepare()
        assert isinstance(prepared, DeclaresIdentity)
        assert prepared.identity is None

    @async_test
    async def test_async_splitter_accepts_an_async_input_stream(self) -> None:
        async with (
            maybe_aclosing(as_async(iter([{"x": 1}]))) as source,
            maybe_aclosing(async_split(source)) as branches,
        ):
            first = await anext(branches)
            assert await anext(first) == {"x": 1}
            second = await anext(branches)
            assert isinstance(first, AsyncTeeBranch)
            assert isinstance(second, AsyncTeeBranch)
            await first.aclose()
            await second.aclose()

    @async_test
    async def test_async_splitter_streams_a_long_feed(self) -> None:
        source = AsyncPullLog(_LONG_ROWS)
        first, second = [branch async for branch in async_split(source)]
        assert (await anext(second), await anext(first)) == ({"i": 0}, {"i": 0})
        assert source.pulled == ({"i": 0},)
        assert isinstance(first, AsyncTeeBranch)
        assert isinstance(second, AsyncTeeBranch)
        await first.aclose()
        await second.aclose()

    def test_splitter_resolves_the_context_for_its_parser(self) -> None:
        seen: dict[str, object] = {}

        @splitter(objectify=False)
        def pipe(stream: Stream, _: object, __: object, **kwargs: object) -> Cascade:
            seen.update(kwargs)
            return iter([stream])

        context = Context(inputs={"name": "riko"})
        list(pipe(iter([{"x": 1}]), context=context))
        assert "context" not in seen
        assert seen.get("inputs") == {"name": "riko"}

    def test_sync_splitter_rejects_an_async_input_stream(self) -> None:
        source = cast("Any", as_async(iter([{"x": 1}])))

        with pytest.raises(TypeError, match="cannot read an async stream"):
            next(split(source))

    @pytest.mark.xfail(
        strict=True,
        raises=AssertionError,
        reason="a lazy async feed into a splitter with a synchronous parser is not "
        "yet implemented",
    )
    @async_test
    async def test_async_splitter_with_a_sync_parser_streams_a_long_feed(self) -> None:
        source = AsyncPullLog(_LONG_ROWS)

        def tee_twice(stream: Stream, *args, **kwargs) -> Cascade:
            return iter(itertools.tee(stream, 2))

        pipe = splitter(is_async=True)(tee_twice)
        first, second = [branch async for branch in pipe(source)]
        assert (await anext(second), await anext(first)) == ({"i": 0}, {"i": 0})
        assert len(source.pulled) < 10

    @pytest.mark.xfail(
        strict=True,
        raises=AssertionError,
        reason="resolving per-item conf for an async splitter input is not yet "
        "implemented",
    )
    @async_test
    async def test_async_splitter_resolves_conf_per_item(self) -> None:
        async def parser(
            stream: Feed, objconf: object, tuples: PipeTuples, /, **kwargs: object
        ) -> AsyncCascade:
            items = as_async(tuples) if isinstance(tuples, Iterator) else tuples
            keys = [{"key": conf.default} async for _, conf in items]
            return as_async(iter([as_async(iter(keys))]))

        pipe = splitter({"default": "fallback"}, is_async=True)(parser)
        conf = cast("Conf", {"default": {"subkey": "x"}})
        async with (
            maybe_aclosing(as_async(iter([{"x": 1}, {"x": 2}]))) as source,
            maybe_aclosing(pipe(source, conf=conf)) as branches,
        ):
            branch = await anext(branches)
            assert [item async for item in branch] == [{"key": 1}, {"key": 2}]

    @pytest.mark.xfail(
        strict=True,
        raises=pytest.fail.Exception,
        reason="rejecting a wrongly typed conf value on a direct pipe call is not yet "
        "implemented",
    )
    def test_a_direct_call_rejects_a_string_isolate(self) -> None:
        """A direct call reads it as true."""
        with pytest.raises(InvalidPipelineError):
            list(split(iter([{"n": 1}]), conf={"isolate": "false"}))  # pyright: ignore[reportArgumentType]


class TestAsyncOperatorLaziness:
    """Async operators yield before draining their inputs."""

    @pytest.mark.xfail(
        strict=True,
        raises=AssertionError,
        reason="Feed-native streaming for truncate is not yet implemented: an async "
        "operator whose parser is synchronous materializes its whole async input "
        "before parsing, so truncate pulls its entire source before yielding its "
        "first item",
    )
    @async_test
    async def test_async_truncate_stays_lazy_over_a_long_source(self) -> None:
        """
        Truncate yields its first item without pulling past its count.

        The source is long but finite so the test ends on its own: an endless source
        would rely on a timeout interrupting the materialization.
        """
        source = PullLog(_LONG_ROWS)
        stream = async_truncate(as_async(source), conf={"count": 3})
        assert await anext(stream) == {"i": 0}
        assert len(source.pulled) <= 3

    @pytest.mark.xfail(
        strict=True,
        raises=AssertionError,
        reason="Feed-native streaming for truncate is not yet implemented: the "
        "whole-source read never yields to the event loop, so an endless source "
        "cannot be cancelled",
    )
    @async_test
    async def test_async_truncate_yields_to_the_event_loop_while_draining(self) -> None:
        """
        Truncate lets other tasks run while it reads a long source.

        The source is long but finite so the test ends on its own. It records whether
        a task started beside it ever ran; a read that never checkpoints finishes the
        whole source first, which is why an endless source hangs uncancellably.
        """
        ran = Event()
        saw_loop: list[bool] = []

        async def tick() -> None:
            ran.set()

        def source() -> Stream:
            for i in range(2000):
                saw_loop.append(ran.is_set())
                yield {"i": i}

        async with create_task_group() as tg:
            tg.start_soon(tick)
            stream = async_truncate(as_async(source()), conf={"count": 1})
            assert await anext(stream) == {"i": 0}

        assert any(saw_loop)

    @pytest.mark.xfail(
        strict=True,
        raises=RuntimeError,
        reason="async union reads its secondary input to the end before yielding its "
        "first item, while the synchronous union reads it lazily",
    )
    @async_test
    async def test_async_union_yields_before_draining_a_secondary_input(self) -> None:
        """
        Union yields its first item without draining its secondary input.

        Like the synchronous union, it may read ahead by at most one item. The
        secondary input raises once it is pulled past a guard, so a draining union
        fails instead of running forever.
        """
        pulled: list[int] = []

        def secondary() -> Stream:
            for i in range(10_000):
                if len(pulled) >= 100:
                    raise RuntimeError("the secondary input was read past its guard")

                pulled.append(i)
                yield {"o": i}

        primary = as_async(iter([{"i": 0}, {"i": 1}]))
        stream = async_union(primary, others=[as_async(secondary())])
        assert await anext(stream) == {"i": 0}
        assert len(pulled) <= 1


def _gen_held(closed: list[bool]) -> Stream:
    try:
        for i in range(100):
            yield {"i": i}
    except GeneratorExit:
        closed.append(True)
        raise


HELD_SOURCE_PIPES = [
    pytest.param(truncate_module, {"count": 50}, id="truncate"),
    pytest.param(uniq_module, {"uniq_key": "i"}, id="uniq"),
    pytest.param(
        filter_module,
        {"rule": {"field": "i", "op": "less", "value": 1000}},
        id="filter",
    ),
]


class TestOperatorInputClose:
    """Closing an operator's stream early closes a source the caller still holds."""

    @pytest.mark.xfail(
        strict=True,
        raises=AssertionError,
        reason="Feed-native streaming for these operators is not yet implemented: the "
        "operator wrapper closes only its parser's result, so closing the pipe early "
        "leaves a source the caller still holds open",
    )
    @pytest.mark.parametrize(("module", "conf"), HELD_SOURCE_PIPES)
    def test_closing_sync_early_closes_a_held_source(self, module, conf) -> None:
        closed: list[bool] = []
        source = _gen_held(closed)
        stream = module.pipe(source, conf=conf)

        with maybe_closing(stream):
            assert next(stream) == {"i": 0}

        assert closed == [True]

    @pytest.mark.xfail(
        strict=True,
        raises=AssertionError,
        reason="Feed-native streaming for these operators is not yet implemented: the "
        "operator wrapper closes only its parser's result, so closing the pipe early "
        "leaves a source the caller still holds open",
    )
    @pytest.mark.parametrize(("module", "conf"), HELD_SOURCE_PIPES)
    @async_test
    async def test_closing_async_early_closes_a_held_source(self, module, conf) -> None:
        closed: list[bool] = []
        source = _gen_held(closed)
        stream = module.async_pipe(source, conf=conf)

        async with maybe_aclosing(stream):
            assert await anext(stream) == {"i": 0}

        assert closed == [True]


def _broad(items) -> Any:
    return items


def _ambiguous(items):
    return build_result(items)  # noqa: F821 # pyright: ignore[reportUndefinedVariable]


def _gen_sync(items):
    yield from items


async def _gen_async(items):
    for item in items:
        yield item


def _ann_iterator(items) -> Iterator[int]:
    return iter(items)


def _ann_awaitable(items) -> Awaitable[Iterator[int]]: ...


def _ann_value(items) -> int:
    return len(items)


def _ann_wrapper(items) -> Annotated[Iterator[int], "meta"]:
    return iter(items)


def _alias(items) -> _AliasStream:
    return iter(items)


def _builtin_stream(items):
    return map(str, items)


def _builtin_nonstream(items):
    return list(items)


def _itertools_stream(items):
    return itertools.chain(items)


async def _passthrough(items):
    result = await asyncio.to_thread(map, str, items)
    return result


def _unresolvable(items) -> Nonexistent:  # noqa: F821 # pyright: ignore[reportUndefinedVariable]
    return sum(items)


def _item_alias(items) -> Item:
    return items


def _unavailable_parameter_hint(conf: DynamicConf) -> Stream:
    return iter([dict(conf)])


def _runtime_unresolvable_alias(items) -> _UnavailableAlias:
    return items


async def _async_rows() -> AsyncStream:
    yield {"x": 1}


ASYNC_INPUTS_TO_SYNC_PIPES = [
    pytest.param(
        lambda: loop(iter(PARENTS), embed=async_tok, conf=TOKENIZER_CONF),  # pyright: ignore[reportArgumentType]
        id="loop-async-embed",
    ),
    pytest.param(lambda: union([{"x": 0}], others=[_async_rows()]), id="union"),
    pytest.param(lambda: join([{"x": 0}], other=_async_rows()), id="join"),
]


class TestSyncPipeAsyncInput:
    @pytest.mark.xfail(
        strict=True,
        raises=AssertionError,
        reason="an error naming the async input a synchronous pipe was given is not "
        "yet implemented",
    )
    @pytest.mark.parametrize("call", ASYNC_INPUTS_TO_SYNC_PIPES)
    def test_sync_pipe_names_an_async_input(self, call):
        with pytest.raises(TypeError, match="async input"):
            list(call())


CLASSIFICATIONS = [
    pytest.param(_gen_sync, STREAM, GENERATOR, id="sync-generator"),
    pytest.param(_gen_async, STREAM, GENERATOR, id="async-generator"),
    pytest.param(_ann_iterator, STREAM, ANNOTATION, id="annotated-iterator"),
    pytest.param(_ann_awaitable, STREAM, ANNOTATION, id="annotated-awaitable"),
    pytest.param(_builtin_nonstream, NONSTREAM, AST, id="builtin-nonstream"),
    pytest.param(_unresolvable, NONSTREAM, AST, id="unresolvable-annotation"),
    pytest.param(_ann_value, NONSTREAM, MISSING, id="annotated-value"),
    pytest.param(_ann_wrapper, STREAM, MISSING, id="annotated-wrapper"),
    pytest.param(_alias, STREAM, MISSING, id="type-alias"),
    pytest.param(_item_alias, NONSTREAM, MISSING, id="item-alias"),
    pytest.param(
        _unavailable_parameter_hint, STREAM, ANNOTATION, id="unavailable-parameter-hint"
    ),
    pytest.param(_builtin_stream, STREAM, MISSING, id="builtin-stream"),
    pytest.param(_itertools_stream, STREAM, MISSING, id="itertools-stream"),
    pytest.param(_passthrough, STREAM, MISSING, id="passthrough-wrapper"),
]


UNKNOWN_REASONS = [
    pytest.param(_broad, ("too broad",), id="broad-annotation"),
    pytest.param(
        _runtime_unresolvable_alias,
        ("not available at runtime",),
        id="runtime-unresolvable-alias",
    ),
    pytest.param(len, ("return annotation",), id="unavailable-source"),
    pytest.param(_ambiguous, ("build_result", "return annotation"), id="ambiguous"),
    pytest.param(
        lambda items: undefined(items),  # noqa: F821, PLW0108 # pyright: ignore[reportUndefinedVariable]
        ("no function definition", "return annotation"),
        id="lambda-in-expression",
    ),
]


def _opaque_parser(
    item: object, extraction: object, objconf: DynamicConf, **kwargs: object
) -> Any:
    return item


def only(pipe):
    return next(iter(gen_return_inferences(pipe)))


class TestReturnInference:
    """Return-kind inference and its diagnostics."""

    @pytest.mark.parametrize(("pipe", "kind", "source"), CLASSIFICATIONS)
    def test_classification(self, pipe, kind, source):
        inference = only(pipe)
        assert inference.kind is kind

        if source is not MISSING:
            assert inference.source is source

    @pytest.mark.parametrize(("pipe", "reasons"), UNKNOWN_REASONS)
    def test_unknown_with_reason(self, pipe, reasons):
        inference = only(pipe)
        assert inference.kind is UNKNOWN
        assert inference.source is None
        assert inference.reason is not None

        for reason in reasons:
            assert reason in inference.reason

    def test_a_processor_of_unknown_return_kind_declares_no_identity(self):
        prepared = processor()(_opaque_parser).prepare()
        assert isinstance(prepared, DeclaresIdentity)
        assert prepared.identity is None

    def test_nested_decorator_with_wraps(self):
        def deco(fn):
            @wraps(fn)
            def inner(*args, **kwargs):
                return fn(*args, **kwargs)

            return inner

        @deco
        def pipe(items):
            return sum(items)

        assert only(pipe).kind is NONSTREAM

    def test_gen_operator_return_kinds_yields_bare_kinds(self):
        def pipe(items) -> Iterator[int] | int:
            return iter(items)

        assert set(gen_operator_return_kinds(pipe)) == {STREAM, NONSTREAM}

    def test_return_kinds_are_inferred_once_per_function(self, monkeypatch):
        calls = []

        def counting(pipe):
            calls.append(pipe)
            return gen_operator_return_kinds(pipe)

        def pipe(items) -> int:
            return sum(items)

        monkeypatch.setattr(_inference, "gen_operator_return_kinds", counting)
        kinds = (infer_return_kinds(pipe), infer_return_kinds(pipe))
        assert kinds == (frozenset({NONSTREAM}),) * 2
        assert calls == [pipe]

    def test_unclassifiable_operator_error_explains_why(self):
        def pipe(items) -> Any:
            return items

        match = r"no supported subtypes found: .*too broad"

        with pytest.raises(TypeError, match=match):
            operator()(pipe)  # pyright: ignore[reportArgumentType, reportCallIssue]


class TestModuleMetadata:
    """Derived module metadata and its classification."""

    def test_undecorated_pipe_is_named_in_the_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        module = ModuleType("riko.modules.bare")
        module.pipe = lambda *args, **kwargs: iter(())  # pyright: ignore[reportAttributeAccessIssue]
        monkeypatch.setattr(_metadata, "import_or_else", lambda *_: module)

        with pytest.raises(TypeError, match=r"riko\.modules\.bare pipe has no module"):
            get_module_metadata("bare")

    @pytest.mark.xfail(
        strict=True,
        raises=AssertionError,
        reason="module flags declared on the decorator are not yet implemented: a "
        "plugin module named like a built-in inherits the built-in's flags",
    )
    def test_plugin_named_like_a_builtin_keeps_its_own_flags(self) -> None:
        def parser(stream, objconf, tuples, **kwargs):
            return iter(stream)

        parser.__module__ = "acme.union"
        assert operator(parser).sequential_inputs is False


def _carries_wrapper_meta(func: object) -> bool:
    return all(hasattr(func, attr) for attr in WRAPPER_META)


WRAPPER_REQUIRES = [
    pytest.param(require_sync_wrapper, "not a sync pipe callable", id="sync"),
    pytest.param(require_async_wrapper, "not an async pipe callable", id="async"),
]


class TestWrapperMeta:
    """Every way of building a pipe stamps the wrapper metadata."""

    def test_stamped_function_carries_wrapper_meta(self):
        def pipe(item=None, **kwargs):
            return iter([])

        stamp_wrapper_meta(
            pipe,
            name="mine",
            module_type="processor",
            subtype="transformer",
            subtypes={"transformer"},
            pollable=False,
            loopable=True,
            is_async=False,
        )
        assert _carries_wrapper_meta(pipe)
        assert isinstance(cast("SyncModuleWrapper", pipe).subtypes, frozenset)

    def test_workflow_decorator_carries_wrapper_meta(self):
        def pipe(item=None, **kwargs):
            return iter([])

        async def async_pipe(item=None, **kwargs):
            yield {}

        def other(item=None, **kwargs):
            return iter([])

        sync_subpipe = workflow()(pipe)
        async_subpipe = workflow()(async_pipe)

        assert _carries_wrapper_meta(sync_subpipe)
        assert _carries_wrapper_meta(async_subpipe)
        assert not sync_subpipe.is_async
        assert async_subpipe.is_async
        assert workflow(is_async=True)(other).is_async

    def test_an_explicit_async_flag_over_a_sync_parser_is_stamped(self):
        wrapped = processor(is_async=True)(shout)
        known = {"name": "test_modules", "type": "processor", "is_async": True}

        assert wrapped.is_async is True
        assert {attr: getattr(wrapped, attr) for attr in known} == known
        assert all(getattr(wrapped, attr) is not None for attr in WRAPPER_META)

    @pytest.mark.parametrize(("require", "match"), WRAPPER_REQUIRES)
    def test_require_rejects_a_plain_function(self, require, match):
        with pytest.raises(TypeError, match=match):
            require(len)


def _tokenizer_loop(
    source: Stream, field="title", **kwargs
) -> SyncOperatorWrapperOutput:
    return loop(source, embed=tokenizer, conf=TOKENIZER_CONF, field=field, **kwargs)


def _custom_embed(item=None, **_):
    return iter([{"content": "x"}])


LOOP_FOLD_CASES = [
    pytest.param(
        {"count": "all", "emit": True},
        [{"content": "a"}, {"content": "b"}, {"content": "c"}, {"content": "d"}],
        id="emit-all",
    ),
    pytest.param(
        {"count": "first", "emit": True},
        [{"content": "a"}, {"content": "c"}],
        id="emit-first",
    ),
    pytest.param(
        {"count": "first", "assign": "first", "emit": False},
        [
            {"title": "a b", "first": {"content": "a"}},
            {"title": "c d", "first": {"content": "c"}},
        ],
        id="assign-first",
    ),
    pytest.param(
        {"count": "all", "assign": "x", "emit": False},
        [
            {"title": "a b", "x": {"content": "a"}},
            {"title": "a b", "x": {"content": "b"}},
            {"title": "c d", "x": {"content": "c"}},
            {"title": "c d", "x": {"content": "d"}},
        ],
        id="assign-all",
    ),
]


SUBPIPE_FOLD_CASES = [
    pytest.param(
        {"count": "all", "emit": True},
        [{"content": "AB"}, {"content": "ba"}, {"content": "CD"}, {"content": "dc"}],
        id="emit-all",
    ),
    pytest.param(
        {"count": "first", "emit": True},
        [{"content": "AB"}, {"content": "CD"}],
        id="emit-first",
    ),
    pytest.param(
        {"count": "first", "assign": "up", "emit": False},
        [
            {"title": "ab", "up": {"content": "AB"}},
            {"title": "cd", "up": {"content": "CD"}},
        ],
        id="assign-first",
    ),
]


ASYNC_SUBPIPE_FOLD_CASES = [SUBPIPE_FOLD_CASES[0], SUBPIPE_FOLD_CASES[2]]


UNEMBEDDABLE = [
    pytest.param(_custom_embed, "Custom embedded modules", id="custom"),
    pytest.param(count_module.pipe, "count is not loopable", id="not-loopable"),
    pytest.param("count", "No embedded module provided", id="not-a-module"),
]


class TestLoop:
    """
    The explicit loop runs its embed once per parent and folds against that parent.

    ``embed`` is the sub-pipe callable and ``conf`` its own conf; ``count``,
    ``emit``, ``assign``, and ``field`` are top-level kwargs. Every stream has at
    least two parents, since one parent cannot expose a global-vs-per-parent
    ``count`` gap.
    """

    def test_loop_prepares_embed_once_per_stream(self, monkeypatch):
        prepares: list[object] = []
        prepare = tokenizer.prepare
        spy = lambda *a, **k: prepares.append(k) or prepare(*a, **k)
        monkeypatch.setattr(tokenizer, "prepare", spy)
        result = _tokenizer_loop(iter(PARENTS), emit=True)
        assert list(result) == [
            {"content": "a"},
            {"content": "b"},
            {"content": "c"},
            {"content": "d"},
        ]
        assert len(prepares) == 1

    @pytest.mark.parametrize(("kwargs", "expected"), LOOP_FOLD_CASES)
    def test_loop_fold(self, kwargs, expected):
        result = _tokenizer_loop(iter(PARENTS), **kwargs)
        assert list(result) == expected

    def test_loop_zero_results_emit_skips_parent(self):
        parents = iter([{"title": ""}, {"title": "x y"}])
        result = _tokenizer_loop(parents, count="all", emit=True)
        assert list(result) == [{"content": "x"}, {"content": "y"}]

    def test_loop_zero_results_assign_preserves_parent(self):
        parents = iter([{"title": ""}, {"title": "x y"}])
        result = _tokenizer_loop(parents, count="all", assign="w", emit=False)
        assert list(result) == [
            {"title": ""},
            {"title": "x y", "w": {"content": "x"}},
            {"title": "x y", "w": {"content": "y"}},
        ]

    def test_loop_level_field_selects_child_input(self):
        parents = iter([{"title": "a b", "alt": "x y"}])
        result = _tokenizer_loop(parents, field="alt", count="all", emit=True)
        assert list(result) == [{"content": "x"}, {"content": "y"}]

    def test_loop_dynamic_conf_resolves_per_parent(self):
        parents = iter([{"title": "aa"}, {"title": "bb"}])
        conf = StrconcatRawConf(
            {
                "part": [
                    {"type": "text", "subkey": "title"},
                    {"type": "text", "value": "!"},
                ]
            }
        )
        result = loop(parents, embed=strconcat, conf=conf, count="all", emit=True)
        assert list(result) == ["aa!", "bb!"]

    @pytest.mark.parametrize(("kwargs", "expected"), SUBPIPE_FOLD_CASES)
    def test_subpipe_fold_per_parent(self, kwargs, expected):
        result = loop(iter(SUBPIPE_PARENTS), embed=_SYNC_SUBPIPE, **kwargs)
        assert list(result) == expected

    def test_subpipe_count_first_is_lazy_and_closes_child(self):
        produced: list[int] = []
        closed: list[str] = []
        embed = build_lazy_embed(produced, closed)
        parents = [{"title": "a"}, {"title": "b"}]
        result = loop(iter(parents), embed=embed, count="first", emit=True)

        assert list(result) == [{"content": "a0"}, {"content": "b0"}]
        assert produced == [0, 0]
        assert closed == ["a", "b"]

    def test_closing_the_loop_closes_the_running_child(self):
        # Not a generator, so only an explicit close can end it.
        closed: list[str] = []

        class Child:
            def __init__(self, tag: str) -> None:
                self.tag, self.index = tag, 0

            def __iter__(self) -> Child:
                return self

            def __next__(self) -> Item:
                self.index += 1
                return {"content": f"{self.tag}{self.index}"}

            def close(self) -> None:
                closed.append(self.tag)

        def _sub(item, context=None, **_):
            return Child(str(item["title"]))

        parents = [{"title": "a"}, {"title": "b"}]
        stream = loop(iter(parents), embed=workflow()(_sub), count="all", emit=True)

        assert isinstance(stream, Generator)
        assert next(stream) == {"content": "a1"}
        stream.close()
        assert closed == ["a"]

    @pytest.mark.parametrize(("embed", "message"), UNEMBEDDABLE)
    def test_unembeddable_embed_passes_parents_through(self, embed, message, caplog):
        result = loop(iter(PARENTS), embed=embed)

        assert list(result) == PARENTS
        assert any(message in r.message for r in caplog.records)


@skipif_sync
class TestAsyncLoop:
    """Async loop preserves the sync per-parent fold and laziness contract."""

    @pytest.mark.parametrize(("kwargs", "expected"), LOOP_FOLD_CASES)
    @pytest.mark.anyio
    async def test_fold_per_parent(self, kwargs, expected):
        stream = async_loop(
            iter(PARENTS), embed=async_tok, conf=TOKENIZER_CONF, field="title", **kwargs
        )
        result = [item async for item in stream]
        assert result == expected

    @pytest.mark.anyio
    async def test_prepares_embed_once_per_stream(self, monkeypatch):
        prepares: list[object] = []
        prepare = async_tok.prepare
        spy = lambda *a, **k: prepares.append(k) or prepare(*a, **k)
        monkeypatch.setattr(async_tok, "prepare", spy)
        stream = async_loop(
            iter(PARENTS),
            embed=async_tok,
            conf=TOKENIZER_CONF,
            field="title",
            emit=True,
        )
        result = [item async for item in stream]
        assert len(result) == 4
        assert len(prepares) == 1

    @pytest.mark.anyio
    async def test_async_loop_is_lazy_and_ordered(self):
        source = PullLog(PARENTS)
        stream = async_loop(
            source,
            embed=async_tok,
            conf=TOKENIZER_CONF,
            field="title",
            count="all",
            emit=True,
        )

        async with maybe_aclosing(stream):
            first = await anext(stream)

        assert first == {"content": "a"}
        assert source.pulled == tuple(PARENTS[:1])

    @pytest.mark.parametrize(("kwargs", "expected"), ASYNC_SUBPIPE_FOLD_CASES)
    @pytest.mark.anyio
    async def test_subpipe_fold_per_parent(self, kwargs, expected):
        stream = async_loop(iter(SUBPIPE_PARENTS), embed=_ASYNC_SUBPIPE, **kwargs)
        result = [item async for item in stream]
        assert result == expected

    @pytest.mark.anyio
    async def test_subpipe_count_first_is_lazy_and_closes_child(self):
        produced: list[int] = []
        closed: list[str] = []

        async def _sub(item, context=None, **_):
            return gen_lazy_child(str(item["title"]), produced, closed)

        stream = async_loop(
            iter([{"title": "a"}, {"title": "b"}]),
            embed=workflow()(_sub),
            count="first",
            emit=True,
        )

        result = [item async for item in stream]
        assert result == [{"content": "a0"}, {"content": "b0"}]
        assert produced == [0, 0]
        assert closed == ["a", "b"]

    @async_test
    async def test_closing_the_loop_closes_the_running_child(self):
        closed: list[str] = []
        embed = build_async_lazy_embed([], closed)
        stream = async_loop(
            iter([{"title": "a"}, {"title": "b"}]), embed=embed, emit=True
        )

        assert isinstance(stream, AsyncGenerator)
        assert await anext(stream) == {"content": "a0"}
        await stream.aclose()
        assert closed == ["a"]

    @pytest.mark.parametrize(("embed", "message"), UNEMBEDDABLE)
    @pytest.mark.anyio
    async def test_unembeddable_embed_passes_parents_through(
        self, embed, message, caplog
    ):
        stream = async_loop(iter(PARENTS), embed=embed)

        assert [item async for item in stream] == PARENTS
        assert any(message in r.message for r in caplog.records)

    @pytest.mark.xfail(
        strict=True,
        raises=RuntimeError,
        reason="streaming an endless async input through the async loop is not yet "
        "implemented: it reads the whole input before running the embed",
    )
    @async_test
    async def test_async_loop_yields_from_an_endless_source(self) -> None:
        """
        Loop yields its first item without draining its source.

        The source raises once it is pulled past a guard, so a draining loop fails
        instead of running forever.
        """
        pulled: list[int] = []

        async def source() -> AsyncStream:
            for i in range(10_000):
                if len(pulled) >= 100:
                    raise RuntimeError("the source was read past its guard")

                pulled.append(i)
                await async_sleep(0)
                yield {"title": f"a{i} b"}

        stream = async_loop(
            source(), embed=async_tok, conf=TOKENIZER_CONF, field="title"
        )
        assert await anext(stream) == {"content": "a0"}


class TestAsyncProcessor:
    """
    A decorated async processor call is both async-iterable and awaitable.

    The default path is ``async for item in async_pipe(...)`` with no outer await;
    awaiting the same call is the advanced path that returns the whole stream. Both
    must hold at once — the call must never collapse to a bare coroutine, which is
    what a ``Generator``-style ``async def`` wrapper stub would produce and what
    breaks ``async for`` under a type checker.
    """

    @async_test
    async def test_call_is_async_iterable_without_outer_await(self):
        async_shout = processor(is_async=True)(shout)
        stream = async_shout({"content": "hi"}, assign="content")
        assert isinstance(stream, AsyncIterator)
        assert [item async for item in stream] == [{"content": "HI"}]

    @async_test
    async def test_awaiting_the_call_returns_the_whole_stream(self):
        async_shout = processor(is_async=True)(shout)
        result = async_shout({"content": "hi"}, assign="content")
        assert isinstance(result, Awaitable)
        assert list(await result) == [{"content": "HI"}]

    @async_test
    async def test_closing_before_reading_ends_the_stream(self):
        calls: list[Item] = []

        def counting(item: Item, *args, **kwargs) -> str:
            calls.append(item)
            return "x"

        stream = processor(is_async=True)(counting)([{"a": 1}], assign="a")

        async with maybe_aclosing(stream):
            pass

        assert [item async for item in stream] == []
        assert calls == []

    @async_test
    async def test_closing_early_closes_the_parser_stream(self):
        closes: list[str] = []
        streams: list[auto_close[str]] = []

        def lines(item: Item, *args, **kwargs) -> auto_close[str]:
            streams.append(auto_close(iter(["a", "b"]), Closable("file", closes)))
            return streams[-1]

        stream = processor(is_async=True)(lines)({"x": 1}, emit=True)
        async with maybe_aclosing(stream):
            await anext(stream)

        assert closes == ["file"]

    def test_wrapper_stubs_are_not_coroutine_functions(self):
        """
        Keep these stubs synchronous for async-iterator typing.

        Changing them to ``async def`` makes the call a bare coroutine, drops
        ``__aiter__``, and restores the ``async for`` type error.
        """
        assert not iscoroutinefunction(AsyncProcessorWrapper.__call__)
        assert not iscoroutinefunction(AsyncSplitterWrapper.__call__)
        assert not iscoroutinefunction(AsyncSubPipe.__call__)

    @pytest.mark.xfail(
        strict=True,
        raises=AssertionError,
        reason="a run-once awaitable async processor result is not yet implemented",
    )
    @async_test
    async def test_awaiting_the_call_twice_runs_the_parser_once(self):
        calls: list[Item] = []

        def counting(item: Item, *args, **kwargs) -> str:
            calls.append(item)
            return "x"

        async_count = processor(is_async=True)(counting)
        result = async_count({"content": "hi"}, assign="content")
        await result
        await result
        assert len(calls) == 1


class TestAsyncOperator:
    @async_test
    async def test_closing_early_closes_the_parser_stream(self):
        closes: list[str] = []
        streams: list[auto_close[Item]] = []

        def lines(*args, **kwargs) -> auto_close[Item]:
            rows = iter([{"x": 1}, {"x": 2}])
            streams.append(auto_close(rows, Closable("file", closes)))
            return streams[-1]

        stream = operator(is_async=True)(lines)([{"x": 0}], emit=True)
        async with maybe_aclosing(stream):
            await anext(stream)

        assert closes == ["file"]


DECORATION_OPTION_CALLS = [
    pytest.param(strconcat, "ftype", id="processor+ftype"),
    pytest.param(count_module.pipe, "ptype", id="operator+ptype"),
    pytest.param(split, "extract", id="splitter+extract"),
]


PICKLED_CONFS = [
    pytest.param({"times": {"type": "int", "value": "2"}}, id="static"),
    pytest.param({"times": {"subkey": "n"}}, id="dynamic"),
]


PER_ITEM_ARGUMENTS = [
    pytest.param("embed", ("embed",), id="declared-embed"),
    pytest.param("others", ("others",), id="declared-others"),
    pytest.param("label", ("label",), id="declared-label"),
    pytest.param("embed", (), id="undeclared-embed"),
    pytest.param("resources", (), id="undeclared-resources"),
]


class TestPrepare:
    @pytest.mark.parametrize(
        ("item", "kind"), [({"content": "a"}, ItemDispatch), ("a", ValueDispatch)]
    )
    def test_dispatch_kind_follows_the_item_shape(self, item, kind):
        prepared = processor().prepare("m", conf={})
        args = (item, prepared.opts)
        kwargs = {"parsers": prepared.parsers, "casters": prepared.casters}
        assert isinstance(resolve_and_cast(*args, **kwargs), kind)

    @pytest.mark.parametrize(
        ("value", "expected"), [(0, [0]), (False, [False]), ("", [""]), (None, [])]
    )
    def test_listize_wraps_falsy_extracted_value(self, value, expected):
        """A falsy (but non-None) extracted value is still list-wrapped."""
        conf = cast("Conf", {"n": value})
        pieces, _ = build_conf(conf, {}, {"extract": "n", "listize": True})
        assert pieces == expected

    def test_extract_matches_the_conf_key_case_insensitively(self):
        conf = cast("Conf", {"n": 1})
        pieces, _ = build_conf(conf, {}, {"extract": "N"})
        assert pieces == 1

    @pytest.mark.parametrize("conf", PICKLED_CONFS)
    def test_a_pickled_prepared_module_rebuilds_its_callables(self, conf):
        prepared = processor(ftype="text").prepare("m", conf=cast("Conf", conf))
        restored = pickle_round_trip(prepared)
        item = {"n": "3", "content": 4}

        assert restored == prepared
        assert restored.parsers.conf_parser(item) == prepared.parsers.conf_parser(item)
        assert restored.casters.field_caster(4) == prepared.casters.field_caster(4)
        assert restored.static_conf == prepared.static_conf

    @pytest.mark.parametrize(
        ("extras", "is_dynamic"), [(("label",), True), ((), False)]
    )
    def test_extras_decide_whether_the_conf_is_dynamic(self, extras, is_dynamic):
        conf = cast("Conf", {"part": {"terminal": "label", "type": "text"}})
        prepared = processor().prepare("m", *extras, conf=conf)

        assert prepared.is_dynamic is is_dynamic
        assert prepared.extras == extras
        assert (prepared.static_casted is None) is is_dynamic

    def test_operator_passes_the_supplied_view_through(self):
        captured = {}

        @operator()
        def pipe(stream: Stream, objconf, tuples, **kwargs) -> Stream:
            captured["view"] = kwargs.get("resources")
            return stream

        view = ResourceView({"resource": Connection()})
        list(pipe([{"a": 1}], resources=view))
        assert captured["view"] is view

    @pytest.mark.parametrize("name", ["wrapper", "items"])
    def test_a_direct_call_passes_an_unknown_keyword_to_the_pipe(self, name):
        captured = {}

        @processor()
        def pipe(item: Item, objconf, tuples, **kwargs) -> Item:
            captured.update(kwargs)
            return item

        kwargs: dict[str, Any] = {name: "value"}
        assert list(pipe([{"a": 1}], **kwargs)) == [{"a": 1}]
        assert captured[name] == "value"

    def test_prepared_module_is_frozen(self):
        conf = cast("Conf", {"x": {"subkey": "y"}})
        prepared = processor(ftype="text").prepare("m", conf=conf)

        with pytest.raises(attrs.exceptions.FrozenInstanceError):
            prepared.name = "other"  # pyright: ignore[reportAttributeAccessIssue]

    @pytest.mark.parametrize(("pipe", "option"), DECORATION_OPTION_CALLS)
    def test_prepare_rejects_a_decoration_option(self, pipe, option):
        kwargs: dict[str, Any] = {option: True}

        with pytest.raises(TypeError, match=f"module fixes '{option}' when it is"):
            pipe.prepare(conf={}, **kwargs)

    @pytest.mark.parametrize(("pipe", "option"), DECORATION_OPTION_CALLS)
    def test_a_direct_call_rejects_a_decoration_option(self, pipe, option):
        kwargs: dict[str, Any] = {option: True}

        with pytest.raises(TypeError, match=f"module fixes '{option}' when it is"):
            list(pipe([{"x": 1}], conf={}, **kwargs))

    @pytest.mark.parametrize(("extra", "extras"), PER_ITEM_ARGUMENTS)
    def test_prepare_rejects_a_per_item_argument(self, extra, extras):
        kwargs: dict[str, Any] = {extra: None}

        with pytest.raises(TypeError, match=f"'strconcat' module takes '{extra}'"):
            strconcat.prepare(*extras, conf={}, **kwargs)

    @pytest.mark.parametrize("option", ["bogus", "wrapper"])
    def test_prepare_rejects_an_unknown_option(self, option):
        kwargs: dict[str, Any] = {option: None}

        with pytest.raises(
            TypeError, match=rf"unknown call options key\(s\): \['{option}'\]"
        ):
            strconcat.prepare(conf={}, **kwargs)

    @pytest.mark.xfail(
        strict=True,
        raises=AssertionError,
        reason=(
            "a frozen per-module config object is not yet implemented: a static "
            "configuration is cast once and the one mutable objconf is handed to "
            "every item, so a parser's write to it reaches the next item"
        ),
    )
    def test_prepared_static_objconf_is_isolated_per_item(self):
        seen: list[int] = []

        @processor()
        def pipe(item: Item, objconf: DynamicConf, tuples: object, **_: object) -> Item:
            seen.append(objconf["count"])
            objconf["count"] += 1
            return item

        list(pipe([{"a": 1}, {"a": 2}], conf={"count": 0}))
        assert seen == [0, 0]


class _FalsyCaster:
    """A caster whose truth value is False."""

    def __len__(self) -> int:
        return 0

    def __call__(self, value: object) -> str:
        return f"<{value}>"


class TestObjectify:
    def test_objectify_applies_a_falsy_func(self):
        assert objectify(5, _FalsyCaster()) == "<5>"


GET_STRING_CASES = [
    pytest.param("a<p>x</p>b", "<p>", "</p>", "x", id="between-markers"),
    pytest.param("<p></p>", "<p>", "</p>", "", id="adjacent-markers"),
    pytest.param("abc", "<p>", "</p>", "", id="missing-start"),
    pytest.param("a<p>xy", "<p>", "</p>", "xy", id="missing-end"),
    pytest.param("abc", "", "c", "ab", id="no-start"),
]


class TestGetString:
    @pytest.mark.parametrize(("content", "start", "end", "expected"), GET_STRING_CASES)
    def test_get_string_slices_between_markers(self, content, start, end, expected):
        assert get_string(content, start, end) == expected


class TestCsvParser:
    @pytest.mark.parametrize("has_header", [True, False])
    @pytest.mark.parametrize("module", [csv, fetchtable], ids=["csv", "fetchtable"])
    def test_empty_csv_yields_no_rows(self, tmp_path, module, has_header):
        path = tmp_path / "empty.csv"
        path.write_text("")
        conf = CsvConf(url=str(path), has_header=has_header)
        assert list(module.pipe(conf=conf)) == []

    @pytest.mark.parametrize("has_header", [True, False])
    @pytest.mark.parametrize("module", [csv, fetchtable], ids=["csv", "fetchtable"])
    @async_test
    async def test_async_empty_csv_yields_no_rows(self, tmp_path, module, has_header):
        path = tmp_path / "empty.csv"
        path.write_text("")
        conf = CsvConf(url=str(path), has_header=has_header)
        assert [item async for item in module.async_pipe(conf=conf)] == []

    def test_csv_headerless_closes_original_source(self, monkeypatch):
        """
        Ensure ``auto_close`` closes the original fetch after header buffering.

        With ``has_header=False``, ``seekable`` uses a spooled copy while leaving the
        original fetch open.
        """
        closed: list[bool] = []
        real_fetch = csv.Fetch

        class _SpyFetch(real_fetch):
            def close(self) -> None:
                closed.append(True)
                super().close()

        monkeypatch.setattr(csv, "Fetch", _SpyFetch)
        conf = CsvObjconf(
            {
                "url": get_path("countries.csv"),
                "has_header": False,
                "skip_rows": 0,
                "col_names": None,
                "encoding": "utf-8",
                "sanitize": False,
                "dedupe": True,
            }
        )

        list(csv.parser({}, None, conf))
        assert closed

    @pytest.mark.parametrize("module", [csv, fetchtable], ids=["csv", "fetchtable"])
    @pytest.mark.xfail(
        strict=True,
        raises=pytest.fail.Exception,
        reason="rejecting a wrongly typed conf value on a direct pipe call is not yet "
        "implemented",
    )
    def test_a_direct_call_rejects_a_string_has_header(self, tmp_path, module) -> None:
        """A bare ``"false"`` is read as true, so the first row becomes the header."""
        path = tmp_path / "rows.csv"
        path.write_text("a,b\n1,2\n")
        conf = CsvConf(url=str(path), has_header="false")  # pyright: ignore[reportArgumentType]
        with pytest.raises(InvalidPipelineError):
            list(module.pipe(conf=conf))


class TestFilter:
    """The ``filter`` module's private clock hook."""

    def test_filter_relative_date_value_resolves_per_evaluation(self, monkeypatch):
        """A ``"today"`` rule value follows the clock, not its first evaluation."""
        ahead, behind = timezone(timedelta(hours=14)), timezone(timedelta(hours=-12))
        items = [{"x": datetime.now(behind).date().isoformat()}]
        rule = FilterConfRule(field="x", op="before", value="today")
        conf = FilterConf({"rule": rule})

        monkeypatch.setattr(cast_module, "load_local_tz", lambda **_: ahead)
        assert list(filter_pipe(items, conf=conf)) == items

        monkeypatch.setattr(cast_module, "load_local_tz", lambda **_: behind)
        assert list(filter_pipe(items, conf=conf)) == []

    def test_filter_allow_inf_flag(self, monkeypatch):
        """Compare infinities numerically when ``ALLOW_INF`` is enabled."""
        items = [{"x": "-inf"}]
        conf = FilterConf({"rule": FilterConfRule(field="x", op="less", value="-5")})

        monkeypatch.setattr("riko.modules.filter.ALLOW_INF", True)
        assert list(filter_pipe(items, conf=conf)) == items

        nan_rule = FilterConfRule(field="x", op="greater", value="9")
        nan_conf = FilterConf({"rule": nan_rule})
        nans = [{"x": "nan"}]
        assert list(filter_pipe(nans, conf=nan_conf)) == nans


# Each row: a rates response document, and the error message it raises.
MISSING_RATES = [
    pytest.param(
        {"error": True, "message": "invalid_app_id", "description": "Invalid App ID"},
        "no or an empty 'rates' mapping: Invalid App ID$",
        id="error-description",
    ),
    pytest.param(
        {"error": True, "message": "not_allowed"},
        "no or an empty 'rates' mapping: not_allowed$",
        id="error-message",
    ),
    pytest.param({"base": "USD"}, "empty 'rates' mapping$", id="no-rates"),
    pytest.param({"rates": [1]}, "empty 'rates' mapping$", id="rates-not-mapping"),
    pytest.param([1], "empty 'rates' mapping$", id="document-not-mapping"),
    pytest.param({"rates": {}}, "empty 'rates' mapping$", id="empty-rates"),
]

# Each row: the response's rate for the currency exchanged from, and the error raised.
UNUSABLE_RATES = [
    pytest.param("abc", "invalid USD/XYZ rate: 'abc'$", id="text"),
    pytest.param([1], r"invalid USD/XYZ rate: \[1\]$", id="list"),
    pytest.param(True, "invalid USD/XYZ rate: True$", id="bool"),
    pytest.param("nan", "invalid USD/XYZ rate: 'nan'$", id="nan"),
    pytest.param("inf", "USD/XYZ rate must be finite: got 'inf'$", id="infinite"),
    pytest.param(0, "USD/XYZ rate must be positive: got 0$", id="zero"),
    pytest.param("-1.2", "USD/XYZ rate must be positive: got '-1.2'$", id="negative"),
]


class TestExchangeRate:
    @async_test
    async def test_data_file_starting_with_http_is_read_locally(
        self, tmp_path, monkeypatch
    ):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "http_quote.json").write_bytes(
            (PACKAGE_DIR / "data" / "quote.json").read_bytes()
        )
        monkeypatch.setattr(paths_module, "PACKAGE_DIR", tmp_path)
        conf = {"url": "http_quote.json", "currency": "USD", "precision": 6}
        rate = await exchangerate_module.async_parser(
            "GBP", None, ExchangeRateObjconf(conf)
        )
        assert str(rate) == "1.275201"

    @async_test
    async def test_http_response_rates_are_read(self, monkeypatch):
        """The HTTP branch reads the ``rates`` mapping out of the response document."""
        document = loads((PACKAGE_DIR / "data" / "quote.json").read_text())

        async def async_get(url: str, **_: object) -> SimpleNamespace:
            return SimpleNamespace(json=lambda: document)

        monkeypatch.setattr(exchangerate_module, "async_get", async_get)
        url = "https://example.com/latest.json"
        conf = {"url": url, "currency": "USD", "precision": 6}
        rate = await exchangerate_module.async_parser(
            "GBP", None, ExchangeRateObjconf(conf)
        )
        assert str(rate) == "1.275201"

    @pytest.mark.parametrize("rate", [None, MISSING], ids=["null", "absent"])
    def test_a_missing_rate_warns_and_is_nan(self, rate, caplog):
        """A currency with no rate in the response yields ``NaN`` and logs a warning."""
        build_rates = exchangerate_module.build_rates
        rates = build_rates(USD=1) if rate is MISSING else build_rates(USD=1, XYZ=rate)
        rate = exchangerate_module.get_cross_rate("XYZ", "USD", places=_PLACES, **rates)
        assert rate.is_nan()
        assert "USD/XYZ rate not found in rates" in caplog.text

    @pytest.mark.parametrize(
        ("extra", "warns"),
        [({"verbose": True}, True), ({"verbose": False}, False), ({}, False)],
        ids=["verbose", "quiet", "default"],
    )
    @pytest.mark.parametrize("is_async", [False, True], ids=["sync", "async"])
    @async_test
    async def test_an_unparseable_rate_warns_only_when_verbose(
        self, extra, warns, is_async, tmp_path, caplog
    ):
        """A bad rate elsewhere in the response warns only with ``verbose`` set."""
        rates_path = tmp_path / "rates.json"
        rates_path.write_text('{"rates": {"USD": 1, "GBP": 2, "XYZ": "bad"}}')
        conf = {"url": str(rates_path), "currency": "USD", "precision": 1}
        objconf = ExchangeRateObjconf({**conf, **extra})
        if is_async:
            rate = await exchangerate_module.async_parser("GBP", None, objconf)
        else:
            rate = exchangerate_module.parser("GBP", None, objconf)

        assert str(rate) == "0.5"
        assert ("invalid rate: 'bad'" in caplog.text) is warns

    @pytest.mark.parametrize(("rate", "match"), UNUSABLE_RATES)
    def test_an_unusable_rate_raises_naming_the_currency(self, rate, match):
        """A rate that isn't a finite positive number raises with the raw value."""
        rates = exchangerate_module.build_rates(USD=1, XYZ=rate)

        with pytest.raises(ValueError, match=match):
            exchangerate_module.get_cross_rate("XYZ", "USD", places=_PLACES, **rates)

    @pytest.mark.parametrize(("document", "match"), MISSING_RATES)
    def test_a_response_without_rates_raises(self, document, match):
        """A rates response with no ``rates`` mapping raises with its own error text."""
        with pytest.raises(ValueError, match=match):
            exchangerate_module.require_rates(document)


async def _drain_receiver(receive_stream: Any, into: list[Item] | None = None) -> None:
    async for item in receive_stream:
        if into is not None:
            into.append(item)


async def _send_first() -> tuple[ItemOrValue, int]:
    source = PullLog(map(dict, _SOURCE_ROWS))
    first: ItemOrValue = {}
    seen = 0

    with fail_after(1):
        async with (
            async_hub.subscribe("r4-lazy") as receive_stream,
            create_task_group() as tg,
        ):
            tg.start_soon(_drain_receiver, receive_stream)
            stream = async_send(source, others=["r4-lazy"])

            async with maybe_aclosing(stream):
                first = await anext(stream)
                seen = len(source.pulled)

    return (first, seen)


async def _send_missing_target(received: list[Item]) -> None:
    with fail_after(1):
        async with (
            async_hub.subscribe("r4-good") as receive_stream,
            create_task_group() as tg,
        ):
            tg.start_soon(_drain_receiver, receive_stream, received)

            with pytest.raises(ReceiverUnavailableError):
                async for _ in async_send(
                    map(dict, _SOURCE_ROWS),
                    conf=SendConf(max_wait=0.05),
                    others=["r4-good", "r4-missing"],
                ):
                    pass


async def _send_feed(received: list[Item]) -> list[ItemOrValue]:
    out: list[ItemOrValue] = []

    with fail_after(1):
        async with (
            async_hub.subscribe("r4-feed") as receive_stream,
            create_task_group() as tg,
        ):
            tg.start_soon(_drain_receiver, receive_stream, received)
            stream = async_send(gen_items(map(dict, _SOURCE_ROWS)), others=["r4-feed"])
            out = [item async for item in stream]

    return out


class TestAsyncSend:
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

    @async_test
    async def test_async_send_accepts_a_feed_source(self):
        """
        An async input stream reaches the parser as an ``AsyncIterator``, not a list.

        ``operator.anormalize_input``/``setup`` hand the parser an async ``orig_stream``
        when the caller passes a ``Feed``. So a sync ``for`` over it raises
        ``TypeError``.
        """
        received: list[Item] = []
        out = await _send_feed(received)

        assert out == _SOURCE_ROWS
        assert received == _SOURCE_ROWS

    @pytest.mark.xfail(
        strict=True,
        raises=AssertionError,
        reason="lazy async fan-out is not yet implemented",
    )
    @async_test
    async def test_async_send_does_not_buffer_its_source(self):
        """Send yields its first item without reading its source past the lookahead."""
        first, seen = await _send_first()

        assert first == {"x": "foo", "i": 0}
        assert seen <= LOOKAHEAD


async def _receive_first() -> tuple[ItemOrValue, int]:
    source = PullLog(map(dict, _SOURCE_ROWS))
    first: ItemOrValue = {}
    seen = 0

    async def _snapshot(receive_stream: Any) -> None:
        nonlocal first, seen
        idx = 0

        async for item in receive_stream:
            if idx == 0:
                first, seen = item, len(source.pulled)

            idx += 1

    with fail_after(1):
        async with (
            async_hub.subscribe("r-recv-lazy") as receive_stream,
            create_task_group() as tg,
        ):
            tg.start_soon(_snapshot, receive_stream)
            async for _ in async_send(source, others=["r-recv-lazy"]):
                pass

    return (first, seen)


class TestAsyncReceive:
    @async_test
    async def test_async_receive_does_not_materialize(self):
        """
        Deliver each item before pulling the next one from the source.

        The zero-buffer channel lets subscribers observe items without materializing
        the source. ``send`` still eagerly collects its own passthrough return; see
        ``test_async_send_does_not_buffer_its_source``.
        """
        first, seen = await _receive_first()

        assert first == {"x": "foo", "i": 0}
        assert seen <= LOOKAHEAD


class TestAsyncTimeoutIterator:
    @pytest.mark.timeout(3)
    @pytest.mark.xfail(
        strict=True,
        raises=AssertionError,
        reason="AsyncTimeoutIterator only checks its deadline between anexts. A "
        "source that stalls past the deadline is awaited to completion rather than "
        "interrupted.",
    )
    @async_test
    async def test_timeout_interrupts_a_stalled_source(self):
        """A stalled source is abandoned after timeout, not awaited to completion."""

        async def source():
            yield {"x": 0}
            await async_sleep(0.5)
            yield {"x": 1}

        it = AsyncTimeoutIterator(source(), timeout_ms=50)
        start = monotonic()
        [item async for item in it]
        run_time = monotonic() - start
        assert run_time < 0.25


# A processor's one-result stream and the item it assigns into ``y``.
FIRST_RESULTS = [
    pytest.param((), {"x": 1}, id="empty"),
    pytest.param((None,), {"x": 1, "y": None}, id="none"),
]


class TestGenAssignments:
    @pytest.mark.parametrize(("results", "expected"), FIRST_RESULTS)
    def test_first_result_is_assigned_unless_absent(self, results, expected) -> None:
        item, stream = DotDict({"x": 1}), iter(results)
        assert list(gen_assignments(item, stream, assign="y", one=True)) == [expected]
