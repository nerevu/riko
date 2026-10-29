# vim: sw=4:ts=4:expandtab
"""Provides internal tests for module decorators, metadata, loops, and resolvers."""

from __future__ import annotations

import asyncio
import copy
import itertools
import pickle  # noqa: S403
from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Iterator
from functools import wraps
from inspect import isawaitable, iscoroutinefunction
from time import monotonic
from types import ModuleType, SimpleNamespace
from typing import TYPE_CHECKING, Annotated, Any, Literal, assert_type, cast

import attrs
import pytest

from riko.bado._backend import async_sleep, create_task_group
from riko.bado.itertools import as_async
from riko.base import _paths as paths_module
from riko.base._exceptions import (
    InvalidPipelineError,
    ReceiverUnavailableError,
    UnsupportedModuleError,
    UnsupportedWorkflowError,
)
from riko.base._guards import is_mapping
from riko.base._paths import PACKAGE_DIR, TESTS_DIR, get_path
from riko.base._sentinels import MISSING
from riko.coercion._configs import CsvObjconf, ExchangeRateObjconf
from riko.definitions._context import Context
from riko.definitions._module_definition import ModuleDefinition
from riko.definitions._workflow_definition import Workflow
from riko.definitions._wrapping import stamp_wrapper_meta
from riko.execution._resource_view import ResourceView
from riko.modules import _metadata, csv, describe_module
from riko.modules import count as count_module
from riko.modules import exchangerate as exchangerate_module
from riko.modules import regex as regex_module
from riko.modules import tokenizer as tokenizer_module
from riko.modules._decorators import operator, processor, splitter
from riko.modules._inference import gen_operator_return_kinds, gen_return_inferences
from riko.modules._metadata import get_module_metadata, list_modules
from riko.modules._prepare import build_conf, resolve_and_cast
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
from riko.modules.truncate import pipe as truncate
from riko.modules.union import async_pipe as async_union
from riko.runtime._importutils import require_interface
from riko.runtime._module_registry import (
    module_registry,
    register_module,
    reset_module_registry,
)
from riko.runtime._pipeline import Pipeline
from riko.runtime._pubsub import async_hub
from riko.runtime._resolver import ResolverDispatcher, dispatcher
from riko.runtime._workflow_pipes import build_workflow_pipes, workflow
from riko.runtime._workflow_resolver import WorkflowResolver
from riko.runtime._workflow_stores import (
    CompositeStore,
    DirectoryStore,
    MappingStore,
    PackageStore,
)
from riko.types._enums import ExecutionMode
from riko.types._options import ItemDispatch, ValueDispatch
from riko.types._wrappers import (
    WRAPPER_META,
    AsyncProcessorWrapper,
    AsyncSplitterWrapper,
    AsyncSubPipe,
    SyncProcessorWrapper,
    require_async_wrapper,
    require_sync_wrapper,
)
from riko.types.modules import (
    Conf,
    InferenceSource,
    OperatorReturnKind,
    SendConf,
    StrconcatRawConf,
    TokenizerRawConf,
)
from tests import async_test, pyworkflows, skipif_issync
from tests._execution import module_workflow, registered_modules
from tests._lifecycle import LOOKAHEAD
from tests._resources import Connection
from tests._workflows import EXCLAIMED, PARENT, register_documents

if TYPE_CHECKING:
    from riko.types._streams import AsyncStream, Cascade, Item, ItemOrValue, Stream
    from riko.types._wrappers import SyncModuleWrapper, SyncOperatorWrapperOutput


def shout(item: Item, *args, **kwargs) -> str:
    return str(item.get("content", "")).upper()


PARENTS = [{"title": "a b"}, {"title": "c d"}]
TOKENIZER_CONF = TokenizerRawConf({"delimiter": {"type": "text", "value": " "}})


_NAME = "acme.mod"
_MISSING_NAME = "nope"


@pytest.fixture
def fixed_registry():
    with registered_modules() as registry:
        yield registry


marker = cast("SyncModuleWrapper", lambda source, **_: source)
MOD_DEFN = ModuleDefinition(name=_NAME, sync_pipe=marker)


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
    resolved = await value if isawaitable(value) else value

    if isinstance(resolved, AsyncIterable):
        result = [await _drain(part) async for part in resolved]
    elif isinstance(resolved, Iterator):
        result = [await _drain(part) for part in resolved]
    else:
        result = resolved

    return result


BARE_ROWS = [{"content": "hi"}]
BARE_FORMS = [
    pytest.param(processor, shout, {"assign": "content"}, id="processor-sync"),
    pytest.param(processor, _async_shout, {"assign": "content"}, id="processor-async"),
    pytest.param(operator, _count, {}, id="operator-sync"),
    pytest.param(operator, _async_count, {}, id="operator-async"),
    pytest.param(splitter, _twice, {}, id="splitter-sync"),
    pytest.param(splitter, _async_twice, {}, id="splitter-async"),
]
BARE_AND_OPTIONS = [
    pytest.param(processor, (), {"isasync": True}, id="processor+isasync"),
    pytest.param(operator, ({},), {}, id="operator+defaults"),
    pytest.param(splitter, (), {"objectify": False}, id="splitter+objectify"),
]
DECORATORS = [processor, operator, splitter]


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

    @pytest.mark.parametrize(("decorator", "args", "kwargs"), BARE_AND_OPTIONS)
    def test_function_with_options_raises(self, decorator, args, kwargs) -> None:
        with pytest.raises(TypeError, match="either the function to wrap or"):
            decorator(shout, *args, **kwargs)

    @pytest.mark.parametrize("decorator", DECORATORS)
    def test_default_instance_round_trips(self, decorator) -> None:
        copies = [pickle.loads(pickle.dumps(decorator())), copy.copy(decorator())]  # noqa: S301
        assert [type(each) for each in copies] == [decorator, decorator]


def _fixed_processor(item: Item, extraction: object, objconf: object) -> str:
    return str(item.get("content", "")).upper()


def _fixed_operator(stream: Stream, extraction: object, tuples: object) -> int:
    return sum(1 for _ in stream)


def _fixed_splitter(stream: Stream, extraction: object, tuples: object) -> Cascade:
    return iter([stream])


FIXED_ROWS = [{"x": 1}]
FIXED_SPLITTER = splitter(objectify=False)
FIXED_CONTEXT = {"context": Context()}
FIXED_ARITY = [
    pytest.param(processor(), _fixed_processor, {"content": "hi"}, {}, id="processor"),
    pytest.param(operator(), _fixed_operator, FIXED_ROWS, {}, id="operator"),
    pytest.param(
        FIXED_SPLITTER, _fixed_splitter, FIXED_ROWS, FIXED_CONTEXT, id="splitter"
    ),
]


class TestParserSignature:
    """
    The ``**kwargs`` a parser needs for the keyword arguments its decorator passes.

    A parser without ``**kwargs`` is rejected by the type checker at decoration,
    since the call would otherwise fail with ``TypeError`` on the first item.
    """

    def test_processor_parser_with_kwargs_is_accepted(self) -> None:
        def parser(item: Item, extraction: object, objconf: object, **_: object) -> str:
            return str(item.get("content", "")).upper()

        pipe = processor()(parser)
        assert next(pipe({"content": "hi"}, assign="content")) == {"content": "HI"}

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

    def test_undecorated_pipe_is_named_in_the_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        module = ModuleType("riko.modules.bare")
        module.pipe = lambda *args, **kwargs: iter(())  # pyright: ignore[reportAttributeAccessIssue]
        monkeypatch.setattr(_metadata, "import_or_else", lambda *_: module)

        with pytest.raises(TypeError, match=r"riko\.modules\.bare pipe has no module"):
            get_module_metadata("bare")


def _carries_wrapper_meta(func: object) -> bool:
    return all(hasattr(func, attr) for attr in WRAPPER_META)


WRAPPER_REQUIRES = [
    pytest.param(require_sync_wrapper, "synchronous", id="sync"),
    pytest.param(require_async_wrapper, "asynchronous", id="async"),
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
            isasync=False,
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

    @pytest.mark.parametrize(("require", "match"), WRAPPER_REQUIRES)
    def test_require_rejects_a_plain_function(self, require, match):
        with pytest.raises(TypeError, match=match):
            require(len)


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


class TestBuildWorkflowPipes:
    def test_an_unseeded_pipe_requires_a_seed(self):
        flow = module_workflow("reverse")
        pipes = build_workflow_pipes(flow, dispatcher, subtype="transformer")

        with pytest.raises(InvalidPipelineError, match="requires a seed"):
            list(pipes.sync_pipe())


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

    @pytest.mark.parametrize(("embed", "message"), UNEMBEDDABLE)
    def test_unembeddable_embed_passes_parents_through(self, embed, message, caplog):
        result = loop(iter(PARENTS), embed=embed)

        assert list(result) == PARENTS
        assert any(message in r.message for r in caplog.records)


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

    @pytest.mark.parametrize(("embed", "message"), UNEMBEDDABLE)
    @pytest.mark.anyio
    async def test_unembeddable_embed_passes_parents_through(
        self, embed, message, caplog
    ):
        stream = async_loop(iter(PARENTS), embed=embed)

        assert [item async for item in stream] == PARENTS
        assert any(message in r.message for r in caplog.records)


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


class TestProcessor:
    @pytest.mark.parametrize(("kwargs", "expected"), PROCESSOR_FOLD_CASES)
    def test_top_level_fold(self, kwargs, expected):
        item = {"title": "a b c"}
        result = tokenizer(item, conf=TOKENIZER_CONF, field="title", **kwargs)
        assert list(result) == expected

    @pytest.mark.parametrize(("kwargs", "expected"), IMPLICIT_FOLD_CASES)
    def test_stream_fold_per_item(self, kwargs, expected):
        result = tokenizer(iter(PARENTS), conf=TOKENIZER_CONF, field="title", **kwargs)
        assert list(result) == expected

    def test_single_item_is_not_double_mapped(self):
        item = {"title": "a b"}
        result = tokenizer(item, conf=TOKENIZER_CONF, field="title", emit=True)
        assert list(result) == [{"content": "a"}, {"content": "b"}]


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


class _FalsyPipe:
    """A pipe callable whose truthiness is ``False`` but which still has a name."""

    __name__ = "double"

    def __bool__(self) -> bool:
        return False

    def __call__(self, source, **kwargs):
        return source


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

        monkeypatch.setattr("riko.base._typing.import_module", fake_import)

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

    def test_falsy_callable_supplies_name(self):
        pipe = cast("SyncModuleWrapper", _FalsyPipe())
        assert ModuleDefinition(sync_pipe=pipe).name == "double"

    def test_module_convention_snapshots_at_construction(self, fixed_registry):
        other = cast("SyncModuleWrapper", lambda source, **_: source)
        mod = SimpleNamespace(pipe=marker, __name__="pkg.snap")
        definition = ModuleDefinition.from_module(mod)
        fixed_registry.register(definition)
        mod.pipe = other
        mod.__name__ = "pkg.other"

        assert definition.name == "snap"
        assert attrs.evolve(definition, description="z").name == "snap"
        assert fixed_registry.require("snap") is marker

    def test_module_convention_derives_both_interfaces(self, fixed_registry):
        mod = SimpleNamespace(pipe=marker, async_pipe=marker)
        fixed_registry.register(ModuleDefinition.from_module(mod, name=_NAME))

        assert fixed_registry.require(_NAME) is marker
        assert fixed_registry.require(_NAME, True) is marker

    def test_module_convention_description_override(self):
        mod = SimpleNamespace(pipe=marker, __doc__="Shouts.")
        definition = ModuleDefinition.from_module(mod, description="Yells.")
        assert definition.description == "Yells."

    def test_explicit_callable_overrides_module(self, fixed_registry):
        other = cast("SyncModuleWrapper", lambda source, **_: source)
        mod = SimpleNamespace(pipe=other, async_pipe=other)
        derived = ModuleDefinition.from_module(mod, name=_NAME)
        definition = attrs.evolve(derived, sync_pipe=marker)
        fixed_registry.register(definition)

        assert fixed_registry.require(_NAME) is marker  # explicit wins
        assert fixed_registry.require(_NAME, True) is other  # from module


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


class TestPublicRegister:
    """Exercise ``register_module`` against the process-global registry."""

    def test_register_resolves_via_global_registry(self, fixed_registry):
        register_module(MOD_DEFN)
        assert dispatcher.require(_NAME) is marker
        assert module_registry.require(_NAME) is marker

    def test_register_runs_end_to_end(self, fixed_registry):
        """A registered alias of a built-in resolves and runs through a pipeline."""
        register_module(ModuleDefinition.from_module(tokenizer_module, name=_NAME))
        pipeline = Pipeline.from_module(_NAME, conf={"delimiter": " "})
        stream = pipeline([{"content": "a b c"}])
        expected = ["a", "b", "c"]
        assert [item.get("content") for item in stream if is_mapping(item)] == expected

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

    def test_from_module_definition_must_name_the_entry_point(
        self, monkeypatch, fixed_registry
    ):
        """A module-derived name declares the module tail, so the key must match it."""
        mod = SimpleNamespace(pipe=marker, __name__="pkg.shout")
        defn = ModuleDefinition.from_module(mod)
        _patch_entry_points(monkeypatch, _FakeEntryPoint(_NAME, defn))

        with pytest.raises(ValueError, match="must match"):
            fixed_registry.require(_NAME)

        named = ModuleDefinition.from_module(mod, name=_NAME)
        _patch_entry_points(monkeypatch, _FakeEntryPoint(_NAME, named))
        assert fixed_registry.require(_NAME) is marker

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

    def test_load_workflow_accepts_the_colon_alias(self):
        directory = TESTS_DIR / "workflows"
        resolver = WorkflowResolver(document_store=DirectoryStore(directory))
        assert resolver.load_workflow("pipe:gigs") == resolver.load_workflow(
            "pipe_gigs"
        )

    def test_second_document_store_requires_replace(self, tmp_path):
        resolver = WorkflowResolver(document_store=DirectoryStore(tmp_path))

        with pytest.raises(ValueError, match="document store already registered"):
            resolver.register(document_store=DirectoryStore(tmp_path))

    def test_missing_stored_workflow_interfaces_raise(self):
        with pytest.raises(UnsupportedWorkflowError, match="no store supplies"):
            WorkflowResolver().require_interfaces("pipe_missing")


class TestPackageStore:
    def test_a_plain_module_is_not_a_package(self):
        with pytest.raises(ValueError, match="is a module, not a package"):
            PackageStore(tokenizer_module)

    def test_mistyped_package_path_raises_when_built(self):
        with pytest.raises(ModuleNotFoundError, match="no_such_package"):
            PackageStore("tests.no_such_package")


class TestDirectoryStore:
    def test_directory_store_parses_workflow(self):
        directory = TESTS_DIR / "workflows"
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


class TestCompositeStore:
    def test_first_hit_wins(self):
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
    workflows = TESTS_DIR / "workflows"

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

    def test_document_exposes_both_interfaces(self, tmp_path):
        register_documents(tmp_path)
        interfaces = dispatcher.require_interfaces("pipe_exclaim")
        assert interfaces == frozenset({"pipe", "async_pipe"})

    def test_document_describes_dependencies(self, tmp_path):
        register_documents(tmp_path)
        context = Context(ExecutionMode.DESCRIBE_DEPENDENCIES)
        pipe = dispatcher.require("pipe_exclaim")
        assert pipe(context=context) == ["strconcat"]

    @async_test
    async def test_document_runs_async(self, tmp_path):
        register_documents(tmp_path)
        pipe = dispatcher.require("pipe_exclaim", is_async=True)
        items = [item async for item in pipe(as_async(PARENT))]
        assert items == EXCLAIMED

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


DECORATION_OPTION_CALLS = [
    pytest.param(strconcat, "ftype", id="processor+ftype"),
    pytest.param(count_module.pipe, "ptype", id="operator+ptype"),
    pytest.param(split, "extract", id="splitter+extract"),
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

    @pytest.mark.parametrize("extra", ["embed", "others", "label"])
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

    def test_operator_passes_the_supplied_view_through(self):
        captured = {}

        @operator()
        def pipe(stream: Stream, objconf, tuples, **kwargs) -> Stream:
            captured["view"] = kwargs.get("resources")
            return stream

        view = ResourceView({"resource": Connection()})
        list(pipe([{"a": 1}], resources=view))
        assert captured["view"] is view


class TestCsvParser:
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


class TestExchangeRate:
    def test_a_non_numeric_rate_raises(self):
        with pytest.raises(TypeError, match="invalid rate"):
            exchangerate_module.build_rates({"USD": [1]})

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


_SOURCE_LEN = 5


def _finite_source(consumed: list[int]) -> Stream:
    for i in range(_SOURCE_LEN):
        consumed.append(i)
        yield {"x": "foo", "i": i}


async def _afinite_source(consumed: list[int]) -> AsyncStream:
    for i in range(_SOURCE_LEN):
        consumed.append(i)
        yield {"x": "foo", "i": i}


async def _drain_receiver(receive_stream: Any, into: list[Item] | None = None) -> None:
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
        tg.start_soon(_drain_receiver, receive_stream)
        stream = async_send(_finite_source(consumed), others=["r4-lazy"])
        first = await anext(stream)
        seen = len(consumed)

    return (first, seen)


async def _send_missing_target(received: list[Item]) -> None:
    async with (
        async_hub.subscribe("r4-good") as receive_stream,
        create_task_group() as tg,
    ):
        tg.start_soon(_drain_receiver, receive_stream, received)

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
        tg.start_soon(_drain_receiver, receive_stream, received)
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
        assert seen <= LOOKAHEAD

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
        assert seen <= LOOKAHEAD


class TestAsyncTimeoutIterator:
    @pytest.mark.timeout(5)
    @pytest.mark.xfail(
        strict=True,
        reason="AsyncTimeoutIterator only checks its deadline between anexts. A "
        "source that stalls past the deadline is awaited to completion rather than "
        "interrupted.",
    )
    @async_test
    async def test_timeout_interrupts_a_stalled_source(self):
        """A stalled source is abandoned after timeout, not awaited to completion."""

        async def source():
            yield {"x": 0}
            await async_sleep(1.0)
            yield {"x": 1}

        it = AsyncTimeoutIterator(source(), timeout_ms=50)
        start = monotonic()
        [item async for item in it]
        run_time = monotonic() - start
        assert run_time < 0.5
