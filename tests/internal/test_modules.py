# vim: sw=4:ts=4:expandtab
"""Provides internal tests for module decorators, metadata, loops, and resolvers."""

from __future__ import annotations

import asyncio
import itertools
import pickle  # noqa: S403
from collections.abc import AsyncIterator, Awaitable, Iterator
from functools import wraps
from inspect import isawaitable, iscoroutinefunction
from types import ModuleType, SimpleNamespace
from typing import TYPE_CHECKING, Annotated, Any, cast

import attrs
import pytest

from riko.bado.itertools import as_async
from riko.base._paths import ROOT_DIR
from riko.base.exceptions import (
    InvalidPipelineError,
    UnsupportedModuleError,
    UnsupportedWorkflowError,
)
from riko.definitions._context import Context
from riko.definitions._module_definition import ModuleDefinition
from riko.definitions._workflow_definition import Workflow
from riko.modules import _metadata
from riko.modules import count as count_module
from riko.modules import regex as regex_module
from riko.modules import tokenizer as tokenizer_module
from riko.modules._decorators import operator, processor, splitter
from riko.modules._inference import gen_operator_return_kinds, gen_return_inferences
from riko.modules._metadata import get_module_metadata, list_modules
from riko.modules._prepare import build_conf, resolve_and_cast
from riko.modules.loop import async_pipe as async_loop
from riko.modules.loop import pipe as loop
from riko.modules.regex import pipe as regex
from riko.modules.rename import pipe as rename
from riko.modules.split import async_pipe as async_split
from riko.modules.strconcat import pipe as strconcat
from riko.modules.timeout import async_pipe as timeout_async_pipe
from riko.modules.tokenizer import async_pipe as async_tok
from riko.modules.tokenizer import pipe as tokenizer
from riko.modules.truncate import async_pipe as async_truncate
from riko.modules.truncate import pipe as truncate
from riko.modules.union import async_pipe as async_union
from riko.runtime._importutils import require_interface
from riko.runtime._module_registry import (
    module_registry,
    register_module,
    reset_module_registry,
)
from riko.runtime._pipeline import Pipeline
from riko.runtime._resolver import ResolverDispatcher, dispatcher
from riko.runtime._workflow_pipes import workflow
from riko.runtime._workflow_resolver import WorkflowResolver
from riko.runtime._workflow_stores import (
    CompositeStore,
    DirectoryStore,
    MappingStore,
    PackageStore,
)
from riko.types._guards import is_mapping
from riko.types._options import ItemDispatch, ValueDispatch
from riko.types._sentinels import MISSING
from riko.types._wrappers import (
    WRAPPER_META,
    AsyncProcessorWrapper,
    AsyncSplitterWrapper,
    AsyncSubPipe,
    ProcessorWrapper,
    stamp_wrapper_meta,
)
from riko.types.modules import (
    Conf,
    InferenceSource,
    OperatorReturnKind,
    RegexConf,
    RegexConfRule,
    RegexRawConf,
    RegexRawRule,
    RenameConf,
    RenameConfRule,
    StrconcatRawConf,
    TokenizerRawConf,
)
from tests import async_test, pyworkflows, skipif_issync

if TYPE_CHECKING:
    from riko.types._streams import Cascade, Item, Stream
    from riko.types._wrappers import SyncModuleWrapper, SyncOperatorWrapperOutput


def shout(item: Item, *args, **kwargs) -> str:
    return str(item.get("content", "")).upper()


def _create_wrapper(name: str, *, iscoro: bool, isasync: bool) -> ProcessorWrapper:
    """Decorate a fresh function with the given name/awaitability/explicit flag."""

    async def _coro(item, extraction, objconf, **kwargs) -> str:
        return str(item["content"]).upper()

    def _sync(item, extraction, objconf, **kwargs) -> str:
        return str(item["content"]).upper()

    fn = _coro if iscoro else _sync
    fn.__name__ = name
    decorate = processor(isasync=True) if isasync else processor()
    return decorate(fn)


PARENTS = [{"title": "a b"}, {"title": "c d"}]
TOKENIZER_CONF = TokenizerRawConf({"delimiter": {"type": "text", "value": " "}})


def _tokenizer_loop(
    source: Stream, field="title", **kwargs
) -> SyncOperatorWrapperOutput:
    return loop(source, embed=tokenizer, conf=TOKENIZER_CONF, field=field, **kwargs)


def _custom_embed(item=None, **_):
    return iter([{"content": "x"}])


_NAME = "acme.mod"
_MISSING_NAME = "nope"


@pytest.fixture
def fixed_registry():
    module_registry.reset()
    yield module_registry
    module_registry.reset()


marker = cast("SyncModuleWrapper", lambda source, **_: source)
MOD_DEFN = ModuleDefinition(name=_NAME, sync_pipe=marker)


class TestIsasyncInferenceValid:
    """
    Every non-contradictory combination and its resolved ``isasync``.

    ``isasync`` marks which interface a pipe is (``pipe`` or ``async_pipe``), not
    whether the function is a coroutine. It resolves to explicit ``isasync`` OR
    ``async def`` OR name == ``async_pipe``, so it is only needed explicitly for a
    sync callable that is the async interface under another name.
    """

    @pytest.mark.parametrize(
        ("name", "iscoro", "isasync", "expected"),
        [
            pytest.param("pipe", False, False, False, id="sync-pipe"),
            pytest.param("async_pipe", False, False, True, id="sync-async_pipe-name"),
            pytest.param("async_pipe", True, False, True, id="async_def-async_pipe"),
            pytest.param("shout", True, False, True, id="async_def-other-name"),
            pytest.param("shout", False, False, False, id="sync-other-name"),
            pytest.param("shout", False, True, True, id="explicit-required"),
            pytest.param("async_pipe", False, True, True, id="explicit-redundant-name"),
            pytest.param("shout", True, True, True, id="explicit-redundant-async"),
        ],
    )
    def test_resolved_isasync(self, name, iscoro, isasync, expected):
        assert _create_wrapper(name, iscoro=iscoro, isasync=isasync).isasync is expected


class TestInvalidCombinations:
    """A function named ``pipe`` that resolves async — always a contradiction."""

    @pytest.mark.parametrize(
        ("iscoro", "isasync", "reason"),
        [
            pytest.param(True, False, "an async def", id="async_def"),
            pytest.param(False, True, "marked isasync=True", id="isasync=True"),
            pytest.param(True, True, "an async def", id="async_def+isasync=True"),
        ],
    )
    def test_async_named_pipe_raises(self, iscoro, isasync, reason):
        with pytest.raises(TypeError) as excinfo:
            _create_wrapper("pipe", iscoro=iscoro, isasync=isasync)

        message = str(excinfo.value)
        assert "'pipe' is the synchronous interface" in message
        assert "async_pipe" in message
        assert reason in message

    @pytest.mark.parametrize(
        ("decorator", "option", "value"),
        [
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
        ],
    )
    def test_unsupported_option_raises(self, decorator, option, value):
        kwargs: dict[str, object] = {option: value}
        name = decorator.__name__

        with pytest.raises(
            TypeError, match=f"{name} modules do not support the '{option}'"
        ):
            decorator(**kwargs)


class TestAsyncGeneratorSource:
    """An async-generator (Feed) source flows through an async operator wrapper."""

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


class TestAsyncOperatorReturnsStreamDirectly:
    """
    A decorated async operator returns an ``AsyncIterator`` without awaiting.

    The wrapper call boundary must never expose ``Awaitable[AsyncIterator]``. The
    parser's own implementation style (sync generator vs legacy coroutine that
    returns a completed iterable) stays behind the decorator and must not leak
    into the outer call contract.
    """

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


class TestAsyncProcessorDualProtocol:
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
        async_shout = processor(isasync=True)(shout)
        stream = async_shout({"content": "hi"}, assign="content")
        assert isinstance(stream, AsyncIterator)
        assert [item async for item in stream] == [{"content": "HI"}]

    @async_test
    async def test_awaiting_the_call_returns_the_whole_stream(self):
        async_shout = processor(isasync=True)(shout)
        result = async_shout({"content": "hi"}, assign="content")
        assert isinstance(result, Awaitable)
        assert list(await result) == [{"content": "HI"}]

    def test_wrapper_stubs_are_not_coroutine_functions(self):
        """
        Keep these stubs synchronous for async-iterator typing.

        Changing them to ``async def`` makes the call a bare coroutine, drops
        ``__aiter__``, and restores the ``async for`` type error.
        """
        assert not iscoroutinefunction(AsyncProcessorWrapper.__call__)
        assert not iscoroutinefunction(AsyncSplitterWrapper.__call__)
        assert not iscoroutinefunction(AsyncSubPipe.__call__)


class TestProcessorListKeepsTestFlag:
    """A processor called on a list runs each item with the caller's ``test`` flag."""

    @staticmethod
    def _record(seen: list[object]):
        def record(item: Item, *args, **kwargs) -> str:
            seen.append(kwargs.get("test"))
            return "seen"

        return record

    def test_sync_list(self):
        seen: list[object] = []
        pipe = processor()(self._record(seen))
        list(pipe([{"a": 1}, {"a": 2}], test=True))
        assert seen == [True, True]

    @async_test
    async def test_async_list(self):
        seen: list[object] = []
        async_pipe = processor(isasync=True)(self._record(seen))
        _ = [item async for item in async_pipe([{"a": 1}, {"a": 2}], test=True)]
        assert seen == [True, True]


def _skip_marked(item: Item, *args, **kwargs) -> str:
    return "processed"


class TestProcessorSkipIf:
    """A processor's ``skip_if`` passes matching items through untouched."""

    def test_sync(self):
        pipe = processor(skip_if=lambda item: "x" in item)(_skip_marked)
        result = list(pipe([{"x": 1}, {"y": 2}], assign="y"))
        assert result == [{"x": 1}, {"y": "processed"}]

    @async_test
    async def test_async(self):
        async_pipe = processor(isasync=True, skip_if=lambda item: "x" in item)(
            _skip_marked
        )
        stream = async_pipe([{"x": 1}, {"y": 2}], assign="y")
        result = [item async for item in stream]
        assert result == [{"x": 1}, {"y": "processed"}]


class TestBareDecorator:
    """A decorator used without being called first."""

    @pytest.mark.parametrize("decorator", [processor, operator, splitter])
    def test_bare_decorator_raises_at_decoration(self, decorator) -> None:
        """
        Decorating without calling the decorator first is an author error.

        The decorated function would otherwise be swallowed as the positional
        ``defaults`` and the mistake would surface only on the first call.
        """
        with pytest.raises(TypeError, match=rf"@{decorator.__name__}\(\)"):
            decorator(shout)

    @pytest.mark.xfail(
        strict=True,
        reason="owned by the pending callable-pipes decorator work: a bare @processor "
        "(no parentheses) is rejected at decoration instead of wrapping the function "
        "as an unconfigured pipe",
    )
    def test_bare_processor_wraps_an_unconfigured_pipe(self) -> None:
        pipe = processor(shout)  # pyright: ignore[reportArgumentType]
        stream = pipe({"content": "hi"}, assign="content")  # pyright: ignore[reportCallIssue]
        assert next(stream) == {"content": "HI"}


class TestSplitter:
    """The splitter wrapper over async input and context."""

    @pytest.mark.xfail(
        strict=True,
        reason="owned by the pending execution-owned split fan-out work: the async "
        "splitter wrapper reads its input synchronously, so handing it an async "
        "stream raises TypeError instead of yielding the branches",
    )
    @async_test
    async def test_async_splitter_accepts_an_async_input_stream(self) -> None:
        source = as_async(iter([{"x": 1}]))
        branches = async_split(source)  # pyright: ignore[reportArgumentType]
        first = await anext(branches)
        assert next(first) == {"x": 1}

    @pytest.mark.xfail(
        strict=True,
        reason="owned by the pending execution-owned split fan-out work: the splitter "
        "wrapper does not resolve its context, so its parser receives the raw "
        "context object instead of the context's inputs",
    )
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


class TestAsyncOperatorLaziness:
    """Async operators yield before draining their inputs."""

    @pytest.mark.xfail(
        strict=True,
        reason="owned by the pending Feed-native streaming migration of truncate and "
        "the final legacy-seam cleanup: an async operator whose parser is synchronous "
        "materializes its whole async input before parsing, so truncate pulls its "
        "entire source before yielding its first item",
    )
    @async_test
    async def test_async_truncate_stays_lazy_over_a_long_source(self) -> None:
        """
        Truncate yields its first item without pulling past its count.

        The source is long but finite so the test ends on its own: an endless source
        would rely on a timeout interrupting the materialization.
        """
        pulled: list[int] = []

        def source() -> Iterator[Item]:
            for i in range(10_000):
                pulled.append(i)
                yield {"i": i}

        stream = async_truncate(as_async(source()), conf={"count": 3})
        assert await anext(stream) == {"i": 0}
        assert len(pulled) <= 3

    @pytest.mark.xfail(
        strict=True,
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

        def secondary() -> Iterator[Item]:
            for i in range(10_000):
                if len(pulled) >= 100:
                    raise RuntimeError("the secondary input was read past its guard")

                pulled.append(i)
                yield {"o": i}

        primary = as_async(iter([{"i": 0}, {"i": 1}]))
        stream = async_union(primary, others=[as_async(secondary())])
        assert await anext(stream) == {"i": 0}
        assert len(pulled) <= 1


STREAM = OperatorReturnKind.STREAM
NONSTREAM = OperatorReturnKind.NONSTREAM
UNKNOWN = OperatorReturnKind.UNKNOWN
GENERATOR = InferenceSource.GENERATOR
ANNOTATION = InferenceSource.ANNOTATION
AST = InferenceSource.AST

type _AliasStream = Iterator[int]


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


def only(pipe):
    return next(iter(gen_return_inferences(pipe)))


class TestReturnInference:
    """Return-kind inference and its diagnostics."""

    @pytest.mark.parametrize(
        ("pipe", "kind", "source"),
        [
            pytest.param(_gen_sync, STREAM, GENERATOR, id="sync-generator"),
            pytest.param(_gen_async, STREAM, GENERATOR, id="async-generator"),
            pytest.param(_ann_iterator, STREAM, ANNOTATION, id="annotated-iterator"),
            pytest.param(_ann_awaitable, STREAM, ANNOTATION, id="annotated-awaitable"),
            pytest.param(_builtin_nonstream, NONSTREAM, AST, id="builtin-nonstream"),
            pytest.param(_unresolvable, NONSTREAM, AST, id="unresolvable-annotation"),
            pytest.param(_ann_value, NONSTREAM, MISSING, id="annotated-value"),
            pytest.param(_ann_wrapper, STREAM, MISSING, id="annotated-wrapper"),
            pytest.param(_alias, STREAM, MISSING, id="type-alias"),
            pytest.param(_builtin_stream, STREAM, MISSING, id="builtin-stream"),
            pytest.param(_itertools_stream, STREAM, MISSING, id="itertools-stream"),
            pytest.param(_passthrough, STREAM, MISSING, id="passthrough-wrapper"),
        ],
    )
    def test_classification(self, pipe, kind, source):
        inference = only(pipe)
        assert inference.kind is kind

        if source is not MISSING:
            assert inference.source is source

    @pytest.mark.parametrize(
        ("pipe", "reasons"),
        [
            pytest.param(_broad, ("too broad",), id="broad-annotation"),
            pytest.param(len, ("return annotation",), id="unavailable-source"),
            pytest.param(
                _ambiguous, ("build_result", "return annotation"), id="ambiguous-call"
            ),
            pytest.param(
                lambda items: undefined(items),  # noqa: F821, PLW0108 # pyright: ignore[reportUndefinedVariable]
                ("no function definition", "return annotation"),
                id="lambda-in-expression",
            ),
        ],
    )
    def test_unknown_with_reason(self, pipe, reasons):
        inference = only(pipe)
        assert inference.kind is UNKNOWN
        assert inference.source is None
        assert inference.reason is not None

        for reason in reasons:
            assert reason in inference.reason

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

    def test_unclassifiable_operator_error_explains_why(self):
        def pipe(items) -> Any:
            return items

        match = r"no supported subtypes found: .*too broad"

        with pytest.raises(TypeError, match=match):
            operator()(pipe)  # pyright: ignore[reportArgumentType, reportCallIssue]


class TestModuleMetadata:
    """Derived module metadata and its classification."""

    def test_operator_metadata(self):
        metadata = get_module_metadata("count", strict=True)
        assert metadata.type == "operator"
        assert metadata.subtype == "aggregator"
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

    def test_undecorated_pipe_is_named_in_the_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        module = ModuleType("riko.modules.bare")
        module.pipe = lambda *args, **kwargs: iter(())  # pyright: ignore[reportAttributeAccessIssue]
        monkeypatch.setattr(_metadata, "import_or_else", lambda *_: module)

        with pytest.raises(TypeError, match=r"riko\.modules\.bare pipe has no module"):
            get_module_metadata("bare")

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

    def test_unknown_module_metadata_raises_when_strict(self):
        with pytest.raises(ValueError, match="has no metadata"):
            get_module_metadata("not_a_builtin_module", strict=True)


def _carries_wrapper_meta(func: object) -> bool:
    return all(hasattr(func, attr) for attr in WRAPPER_META)


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
            isasync=False,
        )
        assert _carries_wrapper_meta(pipe)

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
        assert not sync_subpipe.isasync
        assert async_subpipe.isasync
        assert workflow(isasync=True)(other).isasync

    def test_decorated_wrappers_carry_wrapper_meta(self):
        def shout(item: Item, *args, **kwargs) -> str:
            return str(item.get("content", "")).upper()

        def total(*args: Any, **kwargs: object) -> int:
            return 1

        assert _carries_wrapper_meta(processor()(shout))
        assert _carries_wrapper_meta(processor(isasync=True)(shout))
        assert _carries_wrapper_meta(operator()(total))


class TestWorkflowDecorator:
    def test_returns_a_tagged_copy(self):
        tagged = workflow(subtype="transformer")(truncate)

        assert tagged is not truncate
        assert truncate.type == "operator"
        assert truncate.name == "truncate"
        assert tagged.type == "pipe"
        assert get_module_metadata("truncate", strict=True).type == "operator"

    def test_rejects_positional_arguments(self):
        with pytest.raises(TypeError, match="Pipeline"):
            workflow(object())  # pyright: ignore[reportCallIssue]


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

PROCESSOR_FOLD_CASES = [
    pytest.param({"count": "first", "emit": True}, [{"content": "a"}], id="first"),
    pytest.param(
        {"count": "all", "emit": True},
        [{"content": "a"}, {"content": "b"}, {"content": "c"}],
        id="all",
    ),
    pytest.param(
        {"count": "first", "assign": "w", "emit": False},
        [{"title": "a b c", "w": {"content": "a"}}],
        id="assign-first",
    ),
]

IMPLICIT_FOLD_CASES = [
    pytest.param(
        {"emit": True},
        [{"content": "a"}, {"content": "b"}, {"content": "c"}, {"content": "d"}],
        id="all",
    ),
    pytest.param(
        {"count": "first", "emit": True},
        [{"content": "a"}, {"content": "c"}],
        id="first-per-item",
    ),
    pytest.param(
        {"count": "first", "assign": "w", "emit": False},
        [
            {"title": "a b", "w": {"content": "a"}},
            {"title": "c d", "w": {"content": "c"}},
        ],
        id="assign-first",
    ),
]

SUBPIPE_PARENTS = [{"title": "ab"}, {"title": "cd"}]
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


async def _async_subpipe(item: Item, context: Context | None = None, **_) -> Stream:
    title = str(item.get("title", ""))
    return iter([{"content": title.upper()}, {"content": title[::-1]}])


def _sync_subpipe(item: Item, context: Context | None = None, **_) -> Stream:
    title = str(item.get("title", ""))
    return iter([{"content": title.upper()}, {"content": title[::-1]}])


_SYNC_SUBPIPE = workflow()(_sync_subpipe)
_ASYNC_SUBPIPE = workflow()(_async_subpipe)


class TestLoopCharacterization:
    """
    The explicit loop runs its embed once per parent and folds against that parent.

    ``embed`` is the sub-pipe callable and ``conf`` its own conf; ``count``,
    ``emit``, ``assign``, and ``field`` are top-level kwargs. Every stream has at
    least two parents, since one parent cannot expose a global-vs-per-parent
    ``count`` gap.
    """

    def test_loop_maps_embed_once_per_parent(self):
        rule = RegexRawRule(
            {
                "field": {"type": "text", "value": "title"},
                "match": {"type": "text", "value": " "},
                "replace": {"type": "text", "value": "_"},
            }
        )
        result = loop(
            iter(PARENTS),
            embed=regex,
            conf=RegexRawConf({"rule": rule}),
            count="all",
            emit=True,
        )

        assert list(result) == [{"title": "a_b"}, {"title": "c_d"}]

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


class TestProcessorTopLevelCount:
    """Direct processors honor first-class top-level fold kwargs."""

    @pytest.mark.parametrize(("kwargs", "expected"), PROCESSOR_FOLD_CASES)
    def test_fold(self, kwargs, expected):
        item = {"title": "a b c"}
        result = tokenizer(item, conf=TOKENIZER_CONF, field="title", **kwargs)
        assert list(result) == expected


class TestImplicitLooping:
    """A processor fed a stream maps itself over each item like explicit loop."""

    @pytest.mark.parametrize(("kwargs", "expected"), IMPLICIT_FOLD_CASES)
    def test_fold_per_item(self, kwargs, expected):
        result = tokenizer(iter(PARENTS), conf=TOKENIZER_CONF, field="title", **kwargs)
        assert list(result) == expected

    def test_single_item_is_not_double_mapped(self):
        item = {"title": "a b"}
        result = tokenizer(item, conf=TOKENIZER_CONF, field="title", emit=True)
        assert list(result) == [{"content": "a"}, {"content": "b"}]


class TestSubpipeLoop:
    """Stored workflows use the same per-parent fold without sharing execution."""

    @pytest.mark.parametrize(("kwargs", "expected"), SUBPIPE_FOLD_CASES)
    def test_fold_per_parent(self, kwargs, expected):
        result = loop(iter(SUBPIPE_PARENTS), embed=_SYNC_SUBPIPE, **kwargs)
        assert list(result) == expected

    def test_count_first_is_lazy_and_closes_child(self):
        produced: list[int] = []
        closed: list[str] = []

        def child(tag: str):
            try:
                for index in range(50):
                    produced.append(index)
                    yield {"content": f"{tag}{index}"}
            finally:
                closed.append(tag)

        def _sub(item, context=None, **_):
            return child(str(item["title"]))

        parents = [{"title": "a"}, {"title": "b"}]
        result = loop(iter(parents), embed=workflow()(_sub), count="first", emit=True)

        assert list(result) == [{"content": "a0"}, {"content": "b0"}]
        assert produced == [0, 0]
        assert closed == ["a", "b"]


@skipif_issync
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
    async def test_async_loop_is_lazy_and_ordered(self):
        consumed: list[str] = []

        def tracking() -> Stream:
            for parent in PARENTS:
                consumed.append(str(parent["title"]))
                yield parent

        stream = async_loop(
            tracking(),
            embed=async_tok,
            conf=TOKENIZER_CONF,
            field="title",
            count="all",
            emit=True,
        )

        first = await anext(stream)
        assert first == {"content": "a"}
        assert list(consumed) == ["a b"]


@skipif_issync
class TestAsyncSubpipeLoop:
    """Async stored workflows preserve the local per-parent fold contract."""

    @pytest.mark.parametrize(("kwargs", "expected"), ASYNC_SUBPIPE_FOLD_CASES)
    @pytest.mark.anyio
    async def test_fold_per_parent(self, kwargs, expected):
        stream = async_loop(iter(SUBPIPE_PARENTS), embed=_ASYNC_SUBPIPE, **kwargs)
        result = [item async for item in stream]
        assert result == expected

    @pytest.mark.anyio
    async def test_count_first_is_lazy_and_closes_child(self):
        produced: list[int] = []
        closed: list[str] = []

        def child(tag: str):
            try:
                for index in range(50):
                    produced.append(index)
                    yield {"content": f"{tag}{index}"}
            finally:
                closed.append(tag)

        async def _sub(item, context=None, **_):
            return child(str(item["title"]))

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


UNEMBEDDABLE = [
    pytest.param(_custom_embed, "Custom embedded modules", id="custom"),
    pytest.param(count_module.pipe, "count is not loopable", id="not-loopable"),
    pytest.param("count", "No embedded module provided", id="not-a-module"),
]


class TestCustomEmbed:
    """An unembeddable embed is reported and leaves parents untouched."""

    @pytest.mark.parametrize(("embed", "message"), UNEMBEDDABLE)
    def test_passes_parents_through(self, embed, message, caplog):
        result = loop(iter(PARENTS), embed=embed)

        assert list(result) == PARENTS
        assert any(message in r.message for r in caplog.records)


@skipif_issync
class TestAsyncCustomEmbed:
    """The async loop treats an unembeddable embed the same way as the sync loop."""

    @pytest.mark.parametrize(("embed", "message"), UNEMBEDDABLE)
    @pytest.mark.anyio
    async def test_passes_parents_through(self, embed, message, caplog):
        stream = async_loop(iter(PARENTS), embed=embed)

        assert [item async for item in stream] == PARENTS
        assert any(message in r.message for r in caplog.records)


class TestModuleRegistry:
    def test_builtin_resolves_lazily(self, fixed_registry):
        assert fixed_registry.require("tokenizer").__name__ == "pipe"

    @pytest.mark.parametrize("method", ["require", "require_interfaces"])
    def test_missing_module_hints_at_close_matches(self, fixed_registry, method):
        with pytest.raises(
            UnsupportedModuleError, match=r"did you mean 'truncate'\?"
        ) as e:
            getattr(fixed_registry, method)("trunkate")

        assert e.value.module_name == "trunkate"
        assert e.value.matches == ("truncate",)

    def test_missing_module_without_close_match_keeps_the_bare_message(
        self, fixed_registry
    ):
        with pytest.raises(UnsupportedModuleError) as e:
            fixed_registry.require(_MISSING_NAME)

        assert str(e.value) == f"Unsupported riko module: {_MISSING_NAME}"

    def test_missing_dotted_module_raises_unsupported(self, fixed_registry):
        """
        Rejects a dotted name as an unknown module.

        A dotted name is not a built-in, so the registry refuses it before any
        import is attempted.
        """
        with pytest.raises(UnsupportedModuleError):
            fixed_registry.require("acme.nope")

    def test_transitive_import_error_preserved(self, fixed_registry, monkeypatch):
        """Preserve ``ModuleNotFoundError`` for missing internal dependencies."""

        def fake_import(name, *args, **kwargs):
            if name == "riko.modules.tokenizer":
                raise ModuleNotFoundError("No module named 'ghost'", name="ghost")

            return __import__(name, *args, **kwargs)

        monkeypatch.setattr("riko.base._imports.import_module", fake_import)

        with pytest.raises(ModuleNotFoundError) as e:
            fixed_registry.require("tokenizer")

        assert not isinstance(e.value, UnsupportedModuleError)

    def test_runtime_registration_takes_precedence(self, fixed_registry):
        definition = ModuleDefinition(name="tokenizer", sync_pipe=marker)
        fixed_registry.register(definition, replace=True)
        assert fixed_registry.require("tokenizer") is marker

    def test_register_rejects_builtin_shadow_without_replace(self, fixed_registry):
        with pytest.raises(ValueError, match="shadows a built-in module"):
            fixed_registry.register(ModuleDefinition(name="count", sync_pipe=marker))

        assert fixed_registry.registered_names() == ()

    def test_registered_names_are_sorted(self, fixed_registry):
        fixed_registry.register(ModuleDefinition(name="zeta", sync_pipe=marker))
        fixed_registry.register(ModuleDefinition(name="alpha", sync_pipe=marker))
        assert fixed_registry.registered_names() == ("alpha", "zeta")

    def test_register_rejects_duplicate_without_replace(self, fixed_registry):
        fixed_registry.register(MOD_DEFN)

        with pytest.raises(ValueError, match="already registered"):
            fixed_registry.register(MOD_DEFN)

        fixed_registry.register(MOD_DEFN, replace=True)

    def test_registered_module_missing_interface_raises(self, fixed_registry):
        fixed_registry.register(ModuleDefinition(name=_MISSING_NAME, sync_pipe=marker))

        with pytest.raises(UnsupportedModuleError):
            fixed_registry.require(_MISSING_NAME, True)

    def test_runtime_register_requires_name(self, fixed_registry):
        with pytest.raises(ValueError, match="needs a name"):
            fixed_registry.register(ModuleDefinition(sync_pipe=marker))

    def test_module_convention_derives_both_interfaces(self, fixed_registry):
        mod = SimpleNamespace(pipe=marker, async_pipe=marker)
        fixed_registry.register(ModuleDefinition(name=_NAME, module=mod))

        assert fixed_registry.require(_NAME) is marker
        assert fixed_registry.require(_NAME, True) is marker

    def test_explicit_callable_overrides_module(self, fixed_registry):
        other = cast("SyncModuleWrapper", lambda source, **_: source)
        mod = SimpleNamespace(pipe=other, async_pipe=other)
        definition = ModuleDefinition(name=_NAME, sync_pipe=marker, module=mod)
        fixed_registry.register(definition)

        assert fixed_registry.require(_NAME) is marker  # explicit wins
        assert fixed_registry.require(_NAME, True) is other  # from module


class TestPublicRegister:
    """Exercise ``register_module`` against the process-global registry."""

    def test_register_resolves_via_global_registry(self, fixed_registry):
        register_module(MOD_DEFN)
        assert dispatcher.require(_NAME) is marker
        assert module_registry.require(_NAME) is marker

    def test_register_runs_end_to_end(self, fixed_registry):
        """A registered alias of a built-in resolves and runs through a pipeline."""
        register_module(ModuleDefinition(name=_NAME, module=tokenizer_module))
        source = Pipeline(source=[{"content": "a b c"}])
        pipeline = source.pipe(_NAME, conf={"delimiter": " "})
        expected = ["a", "b", "c"]
        assert [
            item.get("content") for item in pipeline if is_mapping(item)
        ] == expected

    def test_reset_registry_clears_registration(self, fixed_registry):
        register_module(MOD_DEFN)
        reset_module_registry()

        with pytest.raises(UnsupportedModuleError):
            dispatcher.require(_NAME)


class TestResolverDispatcher:
    def test_non_stored_workflow_name_routes_to_module_registry(self, fixed_registry):
        # A plain (non ``pipe_*``) name resolves through the module registry, so a
        # miss surfaces as UnsupportedModuleError, not UnsupportedWorkflowError.
        with pytest.raises(UnsupportedModuleError):
            dispatcher.require(_MISSING_NAME)

    def test_missing_stored_workflow_raises(self):
        with pytest.raises(UnsupportedWorkflowError, match="no store supplies") as err:
            dispatcher.require("pipe_missing")

        assert err.value.pipe_id == "pipe_missing"

    def test_missing_stored_workflow_interfaces_raise(self):
        with pytest.raises(UnsupportedWorkflowError, match="no store supplies"):
            WorkflowResolver().require_interfaces("pipe_missing")

    def test_stored_workflow_without_interfaces_fails_validation_as_a_workflow(self):
        store = MappingStore({"pipe_empty": ModuleType("pipe_empty")})
        resolver = WorkflowResolver(module_store=store)
        local = ResolverDispatcher(module_registry, resolver)

        with pytest.raises(UnsupportedWorkflowError, match="no interfaces"):
            local.validate("pipe_empty")

    @pytest.mark.xfail(
        strict=True,
        reason="a runtime-registered pipe_* module is routed to the workflow "
        "resolver by name prefix and raises UnsupportedWorkflowError.",
    )
    def test_runtime_registered_pipe_prefixed_module_resolves(self, fixed_registry):
        """
        Prefer runtime registrations whose names start with ``pipe_``.

        These registrations must resolve to the registered callable rather than
        stored-workflow (``pipe_<id>``) name routing.
        """
        name = "pipe_transform"
        fixed_registry.register(ModuleDefinition(name=name, sync_pipe=marker))
        assert dispatcher.require(name) is marker


class TestRequireInterface:
    """A missing interface names the right kind of thing and keeps the bare name."""

    def test_missing_builtin_module_is_a_module_error(self):
        with pytest.raises(UnsupportedModuleError) as err:
            require_interface("nope")

        assert err.value.module_name == "nope"

    def test_builtin_module_without_interface_is_a_module_error(self):
        def loader(name):
            return ModuleType(name)

        with pytest.raises(UnsupportedModuleError, match="has no 'async_pipe'") as err:
            require_interface("bare", is_async=True, loader=loader)

        assert err.value.module_name == "bare"

    def test_stored_workflow_without_interface_is_a_workflow_error(self):
        def loader(name):
            return ModuleType(name)

        with pytest.raises(UnsupportedWorkflowError, match="has no 'pipe'") as err:
            require_interface("pipe_bare", builtin=False, loader=loader)

        assert err.value.pipe_id == "pipe_bare"


_DOC = "\nShouts each item.\n\nIgnored trailing prose.\n"


def _patch_entry_points(monkeypatch, *eps):
    ep_func = lambda group: list(eps) if group == "riko.modules" else []
    monkeypatch.setattr("riko.runtime._registry.entry_points", ep_func)
    # invalidate the cache memoized by the fixture's pre-test reset
    module_registry.reset()


class _FakeEntryPoint:
    def __init__(self, name, definition):
        self.name = name
        self._definition = definition

    def load(self):
        return self._definition


class TestEntryPointModules:
    """an external package supplies modules via entry points."""

    def test_entry_point_module_resolves(self, monkeypatch, fixed_registry):

        _patch_entry_points(monkeypatch, _FakeEntryPoint(_NAME, MOD_DEFN))
        assert fixed_registry.require(_NAME) is marker

    def test_name_stamped_from_entry_point_key(self, monkeypatch, fixed_registry):
        """Definition omits name so the registry adopts the entry-point key."""
        defn = ModuleDefinition(sync_pipe=marker)
        _patch_entry_points(monkeypatch, _FakeEntryPoint(_NAME, defn))

        assert fixed_registry.require(_NAME) is marker
        assert fixed_registry._entry_point(_NAME).name == _NAME

    def test_name_key_mismatch_raises(self, monkeypatch, fixed_registry):
        defn = ModuleDefinition(name="acme.other", sync_pipe=marker)
        _patch_entry_points(monkeypatch, _FakeEntryPoint(_NAME, defn))

        with pytest.raises(ValueError, match="must match"):
            fixed_registry.require(_NAME)

    def test_entry_point_may_name_a_bare_module(self, monkeypatch, fixed_registry):
        """The entry point resolves to a module, not a ModuleDefinition."""
        mod = SimpleNamespace(pipe=marker, async_pipe=marker, __doc__=_DOC)
        _patch_entry_points(monkeypatch, _FakeEntryPoint(_NAME, mod))

        assert fixed_registry.require(_NAME) is marker
        assert fixed_registry.require(_NAME, True) is marker

    def test_bare_module_description_from_docstring_summary(
        self, monkeypatch, fixed_registry
    ):
        mod = SimpleNamespace(pipe=marker, __doc__=_DOC)
        _patch_entry_points(monkeypatch, _FakeEntryPoint(_NAME, mod))

        definition = fixed_registry.load_definition(_NAME)
        assert definition.name == _NAME
        assert definition.description == "Shouts each item."

    def test_entry_point_without_interfaces_raises(self, monkeypatch, fixed_registry):
        mod = SimpleNamespace(nope=marker)
        _patch_entry_points(monkeypatch, _FakeEntryPoint(_NAME, mod))

        with pytest.raises(TypeError, match="expected a ModuleDefinition"):
            fixed_registry.require(_NAME)

    def test_runtime_registration_shadows_entry_point(
        self, monkeypatch, fixed_registry
    ):
        ep_marker = cast("SyncModuleWrapper", lambda source, **_: source)
        ep_defn = ModuleDefinition(name=_NAME, sync_pipe=ep_marker)
        _patch_entry_points(monkeypatch, _FakeEntryPoint(_NAME, ep_defn))
        fixed_registry.register(MOD_DEFN, replace=True)
        resolved = fixed_registry.require(_NAME)
        assert resolved is marker
        assert resolved is not ep_marker

    def test_register_rejects_entry_point_shadow_without_replace(
        self, monkeypatch, fixed_registry
    ):
        ep_defn = ModuleDefinition(name=_NAME, sync_pipe=marker)
        _patch_entry_points(monkeypatch, _FakeEntryPoint(_NAME, ep_defn))

        with pytest.raises(ValueError, match="shadows an entry-point module"):
            fixed_registry.register(MOD_DEFN)

    def test_entry_points_discovered_lazily_once(self, monkeypatch, fixed_registry):
        calls = {"n": 0}

        def counting(group):
            calls["n"] += 1
            return []

        monkeypatch.setattr("riko.runtime._registry.entry_points", counting)
        fixed_registry.reset()

        with pytest.raises(UnsupportedModuleError):
            fixed_registry.require(_MISSING_NAME)

        with pytest.raises(UnsupportedModuleError):
            fixed_registry.require(_MISSING_NAME)

        assert calls["n"] == 1


class TestWorkflowResolver:
    def test_core_default_has_no_stored_workflows(self):
        """A bare (unconfigured) resolver finds no pipe_* module and no workflow."""
        resolver = WorkflowResolver()
        assert resolver.load("pipe_x") is None

        with pytest.raises(UnsupportedWorkflowError, match="no document store"):
            resolver.load_workflow("pipe_x")

    @pytest.mark.parametrize(
        "package",
        [
            pytest.param("tests.pyworkflows", id="import-path"),
            pytest.param(pyworkflows, id="package"),
        ],
    )
    def test_configured_resolver_loads_resolved_workflow(self, package):
        resolver = WorkflowResolver(module_store=PackageStore(package))
        assert resolver.load("pipe_kazeeki1") is not None

    def test_interfaces_accept_the_colon_alias(self):
        module = ModuleType("pipe_demo")
        setattr(module, "pipe", tokenizer_module.pipe)  # noqa: B010
        resolver = WorkflowResolver(module_store=MappingStore({"pipe_demo": module}))
        assert resolver.require_interfaces("pipe:demo") == {"pipe"}

    def test_require_tags_a_copy_and_leaves_the_module_pipe_untouched(self):
        def plain(item=None, **kwargs):
            return iter([{"x": 1}])

        module = ModuleType("pipe_demo")
        setattr(module, "pipe", plain)  # noqa: B010
        resolver = WorkflowResolver(module_store=MappingStore({"pipe_demo": module}))
        first = resolver.require("pipe_demo")
        second = resolver.require("pipe_demo")

        assert module.pipe is plain
        assert not hasattr(plain, "type")
        assert first is not plain
        assert second is not plain
        assert first.type == second.type == "pipe"

    def test_require_returns_an_already_tagged_pipe_by_identity(self):
        tagged = workflow(subtype="transformer")(lambda item=None, **_: iter([]))
        module = ModuleType("pipe_demo")
        setattr(module, "pipe", tagged)  # noqa: B010
        resolver = WorkflowResolver(module_store=MappingStore({"pipe_demo": module}))

        assert resolver.require("pipe_demo") is tagged

    def test_async_interface_is_tagged_async_whatever_its_name(self):
        """An async interface not named ``async_pipe`` is still tagged async."""

        async def gen_items(item=None, **kwargs):
            yield {"x": 1}

        module = ModuleType("pipe_demo")
        setattr(module, "pipe", lambda item=None, **kwargs: iter([]))  # noqa: B010
        setattr(module, "async_pipe", gen_items)  # noqa: B010
        resolver = WorkflowResolver(module_store=MappingStore({"pipe_demo": module}))
        assert resolver.require("pipe:demo", is_async=True).isasync
        assert not resolver.require("pipe:demo").isasync

    def test_second_document_store_requires_replace(self, tmp_path):
        resolver = WorkflowResolver(document_store=DirectoryStore(tmp_path))

        with pytest.raises(ValueError, match="document store already registered"):
            resolver.register(document_store=DirectoryStore(tmp_path))

    def test_load_workflow_accepts_the_colon_alias(self):
        directory = ROOT_DIR / "tests" / "workflows"
        resolver = WorkflowResolver(document_store=DirectoryStore(directory))
        assert resolver.load_workflow("pipe:gigs") == resolver.load_workflow(
            "pipe_gigs"
        )

    def test_mistyped_package_path_raises_when_built(self):
        with pytest.raises(ModuleNotFoundError, match="no_such_package"):
            PackageStore("tests.no_such_package")

    def test_a_plain_module_is_not_a_package(self):
        with pytest.raises(ValueError, match="is a module, not a package"):
            PackageStore(tokenizer_module)

    def test_directory_store_parses_workflow(self):
        directory = ROOT_DIR / "tests" / "workflows"
        resolver = WorkflowResolver(document_store=DirectoryStore(directory))
        assert isinstance(resolver.load_workflow("pipe_gigs"), Workflow)

        with pytest.raises(
            UnsupportedWorkflowError, match="no WorkflowDocument"
        ) as err:
            resolver.load_workflow("pipe_missing")

        assert err.value.pipe_id == "pipe_missing"

    def test_directory_store_surfaces_unreadable_documents(self, tmp_path):
        """Only a missing document is a miss; an unreadable one is an error."""
        (tmp_path / "pipe_dir.json").mkdir()
        store = DirectoryStore(tmp_path)
        assert store.load("pipe_absent") is None

        with pytest.raises(OSError, match=r"pipe_dir\.json"):
            store.load("pipe_dir")

    def test_composite_store_first_hit_wins(self):
        store = CompositeStore(
            MappingStore({"pipe_x": tokenizer_module}),
            MappingStore({"pipe_x": regex_module}),
            PackageStore("tests.pyworkflows"),
        )
        assert store.load("pipe_x") is tokenizer_module
        assert store.load("pipe_x") is not regex_module
        assert store.load("absent") is None


_META = {
    "type": "operator",
    "subtype": "composer",
    "subtypes": {"composer"},
    "pollable": False,
    "loopable": False,
    "isasync": False,
}


def _pipe_wrapper(**attrs):
    wrapper = cast("SyncModuleWrapper", lambda source, **_: source)

    for key, value in attrs.items():
        setattr(wrapper, key, value)

    return wrapper


class TestCatalog:
    def test_registered_module_appears_in_catalog(self, fixed_registry):
        pipe = _pipe_wrapper(name=_NAME, **_META)
        fixed_registry.register(ModuleDefinition(name=_NAME, sync_pipe=pipe))

        assert _NAME in list_modules()
        assert "tokenizer" in list_modules()  # built-ins still present

    def test_bare_callable_skipped_in_catalog(self, fixed_registry):
        """Resolvable but carries no metadata."""
        fixed_registry.register(MOD_DEFN)

        assert _NAME not in list_modules()

    def test_list_modules_filters_by_provider(self, fixed_registry):
        pipe = _pipe_wrapper(name=_NAME, **_META)
        fixed_registry.register(ModuleDefinition(name=_NAME, sync_pipe=pipe))
        metadata = list_modules(provider="acme", show_metadata=True)

        assert list_modules(provider="acme") == [_NAME]
        assert metadata[0].provider == "acme"


def _document_resolver(directory, **kwargs) -> WorkflowResolver:
    """Builds a resolver whose document modules run through the global dispatcher."""
    resolver = WorkflowResolver(document_store=DirectoryStore(directory), **kwargs)
    resolver.register_dispatcher(dispatcher)
    return resolver


class TestResolvedDocuments:
    workflows = ROOT_DIR / "tests" / "workflows"

    def test_document_loads_once_with_both_interfaces(self):
        resolver = _document_resolver(self.workflows)
        module = resolver.load("pipe_gigs")

        assert module is not None
        assert callable(module.pipe)
        assert callable(module.async_pipe)
        assert resolver.load("pipe_gigs") is module
        assert resolver.require_interfaces("pipe_gigs") == {"pipe", "async_pipe"}

    def test_reset_forgets_resolved_documents(self):
        resolver = _document_resolver(self.workflows)
        assert resolver.load("pipe_gigs") is not None

        resolver.reset()
        assert resolver.load("pipe_gigs") is None

    def test_replacing_documents_reloads_them(self, tmp_path):
        source = self.workflows / "pipe_gigs.json"
        (tmp_path / "pipe_gigs.json").write_bytes(source.read_bytes())
        resolver = _document_resolver(self.workflows)
        first = resolver.load("pipe_gigs")

        resolver.register(document_store=DirectoryStore(tmp_path), replace=True)
        second = resolver.load("pipe_gigs")

        assert second is not None
        assert second is not first

    def test_module_store_wins_over_document(self):
        store = MappingStore({"pipe_gigs": tokenizer_module})
        resolver = _document_resolver(self.workflows, module_store=store)
        assert resolver.load("pipe_gigs") is tokenizer_module

    def test_malformed_document_raises_invalid_pipeline(self, tmp_path):
        (tmp_path / "pipe_bad.json").write_text("{bad")
        resolver = _document_resolver(tmp_path)

        with pytest.raises(InvalidPipelineError, match="malformed"):
            resolver.require("pipe_bad")

    def test_document_without_dispatcher_raises(self):
        resolver = WorkflowResolver(document_store=DirectoryStore(self.workflows))

        with pytest.raises(UnsupportedWorkflowError, match="no dispatcher"):
            resolver.load("pipe_gigs")

    def test_registering_a_dispatcher_rebuilds_documents(self):
        resolver = _document_resolver(self.workflows)
        first = resolver.load("pipe_gigs")

        resolver.register_dispatcher(dispatcher)
        second = resolver.load("pipe_gigs")

        assert second is not None
        assert second is not first


class TestModules:
    def test_rename_skips_absent_field(self):
        """A rename rule naming an absent field leaves the item untouched."""
        conf = RenameConf({"rule": RenameConfRule(field="content", newval="greeting")})
        assert next(rename({"title": "hi"}, conf=conf)) == {"title": "hi"}

    def test_rename_renames_present_falsy_field(self):
        """A present-but-falsy value is still renamed (absent ≠ present-``None``)."""
        conf = RenameConf({"rule": RenameConfRule(field="content", newval="greeting")})
        assert next(rename({"content": ""}, conf=conf)) == {"greeting": ""}

    def test_regex_skips_absent_field(self):
        """A regex rule naming an absent field leaves the item untouched."""
        conf = RegexConf(
            {"rule": RegexConfRule(field="content", match="l", replace="L")}
        )
        assert next(regex({"title": "hi"}, conf=conf)) == {"title": "hi"}


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

    def test_prepared_module_is_frozen(self):
        conf = cast("Conf", {"x": {"subkey": "y"}})
        prepared = processor(ftype="text").prepare("m", conf=conf)

        with pytest.raises(attrs.exceptions.FrozenInstanceError):
            prepared.name = "other"  # pyright: ignore[reportAttributeAccessIssue]

    @pytest.mark.parametrize(
        "conf",
        [
            pytest.param({"times": {"type": "int", "value": "2"}}, id="static"),
            pytest.param({"times": {"subkey": "n"}}, id="dynamic"),
        ],
    )
    def test_a_pickled_prepared_module_rebuilds_its_callables(self, conf):
        prepared = processor(ftype="text").prepare("m", conf=cast("Conf", conf))
        restored = pickle.loads(pickle.dumps(prepared))  # noqa: S301
        item = {"n": "3", "content": 4}

        assert restored == prepared
        assert restored.parsers.conf_parser(item) == prepared.parsers.conf_parser(item)
        assert restored.casters.field_caster(4) == prepared.casters.field_caster(4)
        assert restored.static_conf == prepared.static_conf

    @pytest.mark.parametrize("extra", ["resources", "embed", "others", "label"])
    def test_prepare_rejects_a_per_item_argument(self, extra):
        kwargs: dict[str, Any] = {extra: None}

        with pytest.raises(TypeError, match=f"'strconcat' module takes '{extra}'"):
            strconcat.prepare(extra, conf={}, **kwargs)

    @pytest.mark.parametrize(
        ("extras", "is_dynamic"), [(("label",), True), ((), False)]
    )
    def test_extras_decide_whether_the_conf_is_dynamic(self, extras, is_dynamic):
        conf = cast("Conf", {"part": {"terminal": "label", "type": "text"}})
        prepared = processor().prepare("m", *extras, conf=conf)

        assert prepared.is_dynamic is is_dynamic
        assert prepared.extras == extras
        assert (prepared.static_casted is None) is is_dynamic

    def test_processor_normalizes_a_none_input_to_an_empty_item(self):
        assert processor().normalize_input(None) == {}

    def test_operator_wraps_a_none_item_as_content(self):
        items = cast("Any", [None])
        assert next(operator().normalize_input(items)) == {"content": None}
