# vim: sw=4:ts=4:expandtab
"""
Run-wide execution settings and environment binding on a ``Pipeline``.

``with_execution`` derives a pipeline whose runs use the given executor,
concurrency ceiling, ordering, event sink, and teardown bound; ``with_context``
and ``with_resource`` bind the environment those runs see. Each derivation leaves
the original untouched and carries through every later chaining step.
"""

from __future__ import annotations

from operator import itemgetter
from typing import TYPE_CHECKING, cast

import pytest

from riko import Context, Executor, Pipeline
from riko.definitions._execution import DEF_EXECUTION_SETTINGS
from riko.definitions._workflow import ModuleNode, Workflow
from riko.execution._execution import AsyncExecution, SyncExecution
from riko.ext.registry import ModuleDefinition, register_module, reset_module_registry
from riko.types._workflow import Endpoint
from riko.types.modules import ItemBuilderConf, ParsedParam
from tests import async_test, skipif_issync

if TYPE_CHECKING:
    from riko.types._wrappers import SyncModuleWrapper

SRC = [{"content": "a"}, {"content": "b"}, {"content": "c"}]
VALUE = "once is 1x,twice is 2x,thrice is 3x"
BUILDER_CONF = ItemBuilderConf(
    {"attrs": ParsedParam({"key": "content", "value": VALUE})}
)
READER = "settings_resource_reader"


class Recorder:
    def __init__(self) -> None:
        self.events: list[object] = []

    def emit(self, event: object) -> None:
        self.events.append(event)


def _tokenized() -> Pipeline:
    """Builds a three-item token stream."""
    source = Pipeline.from_module("itembuilder", conf=BUILDER_CONF)
    return source.tokenizer(options={"emit": True})


def _by_content(items):
    return sorted(items, key=itemgetter("content"))


def _reader_workflow() -> Workflow:
    """Builds a one-node workflow whose module declares a ``primary`` resource."""
    node = ModuleNode(id="n", name=READER, resources={"slot": "primary"})
    return Workflow(
        nodes={node.id: node},
        edges=(),
        outputs={"default": Endpoint(node.id, "out")},
        inputs={},
        resources=("primary",),
    )


@pytest.fixture
def reader():
    def read(_items=None, **kwargs):
        yield {"got": kwargs["resources"]["slot"]}

    reset_module_registry()
    sync_pipe = cast("SyncModuleWrapper", read)
    register_module(ModuleDefinition(name=READER, sync_pipe=sync_pipe))

    try:
        yield READER
    finally:
        reset_module_registry()


class TestWithExecution:
    def test_defaults(self):
        pipeline = Pipeline.from_module("fetch")
        assert pipeline.settings == DEF_EXECUTION_SETTINGS
        assert pipeline.settings.executor is Executor.AUTO
        assert pipeline.settings.concurrency is None
        assert pipeline.settings.ordered is False
        assert pipeline.settings.event_sink is None
        assert pipeline.settings.shutdown_timeout is None
        assert pipeline.context is None

    def test_derives_without_changing_the_original(self):
        base = Pipeline.from_module("fetch")
        pipeline = base.with_execution(concurrency=4, ordered=True)
        assert pipeline is not base
        assert pipeline.workflow == base.workflow
        assert (pipeline.settings.concurrency, pipeline.settings.ordered) == (4, True)
        assert base.settings == DEF_EXECUTION_SETTINGS

    def test_chaining_keeps_the_settings(self):
        pipeline = Pipeline.from_module("fetch").with_execution(concurrency=4)
        chained = [
            pipeline.pipe("sort"),
            pipeline.sort(),
            pipeline | "sort",
            pipeline | ("sort", {"combine": "a"}),
            pipeline | Pipeline.from_module("sort"),
            pipeline.write("out.csv"),
        ]
        assert all(each.settings.concurrency == 4 for each in chained)

    def test_seeding_a_source_keeps_the_settings(self):
        pipeline = Pipeline.from_module("hash").with_execution(executor="thread")
        seeded = SRC | pipeline
        assert seeded.source is SRC
        assert seeded.settings.executor is Executor.THREAD

    @pytest.mark.parametrize(
        ("executor", "expected"),
        [
            ("thread", Executor.THREAD),
            ("inline", Executor.INLINE),
            (Executor.PROCESS, Executor.PROCESS),
            (Executor.AUTO, Executor.AUTO),
        ],
    )
    def test_executor_accepts_strings_and_members(self, executor, expected):
        pipeline = Pipeline.from_module("fetch").with_execution(executor=executor)
        assert pipeline.settings.executor is expected

    @pytest.mark.parametrize(
        ("kwargs", "error"),
        [
            ({"executor": "gpu"}, ValueError),
            ({"concurrency": 0}, ValueError),
            ({"concurrency": "4"}, TypeError),
            ({"ordered": "yes"}, TypeError),
            ({"shutdown_timeout": -1}, ValueError),
            ({"shutdown_timeout": float("nan")}, ValueError),
        ],
    )
    def test_invalid_settings_raise_at_call_time(self, kwargs, error):
        with pytest.raises(error):
            Pipeline.from_module("fetch").with_execution(**kwargs)

    def test_omitted_arguments_keep_the_current_settings(self):
        sink = Recorder()
        pipeline = Pipeline.from_module("fetch").with_execution(
            executor="thread",
            concurrency=4,
            ordered=True,
            event_sink=sink,
            shutdown_timeout=2.5,
        )
        assert pipeline.with_execution().settings == pipeline.settings

    @pytest.mark.parametrize(
        ("name", "value"),
        [
            ("executor", "thread"),
            ("concurrency", 4),
            ("ordered", True),
            ("event_sink", Recorder()),
            ("shutdown_timeout", 2.5),
        ],
    )
    def test_explicit_none_restores_the_default(self, name, value):
        kwargs = {"executor": "process", "concurrency": 8, name: value}
        pipeline = Pipeline.from_module("fetch").with_execution(**kwargs)
        reset = pipeline.with_execution(**{name: None})
        assert getattr(reset.settings, name) == getattr(DEF_EXECUTION_SETTINGS, name)

        if name not in {"executor", "concurrency"}:
            assert reset.settings.executor is Executor.PROCESS
            assert reset.settings.concurrency == 8

    def test_event_sink_reaches_the_execution(self):
        sink = Recorder()
        pipeline = Pipeline.from_module("fetch").with_execution(event_sink=sink)
        execution = SyncExecution(pipeline.context, settings=pipeline.settings)
        assert execution.events is sink

    def test_shutdown_timeout_reaches_the_async_execution(self):
        pipeline = Pipeline.from_module("fetch").with_execution(shutdown_timeout=1.5)
        execution = AsyncExecution(pipeline.context, settings=pipeline.settings)
        assert execution.shutdown_timeout == pytest.approx(1.5)


class TestExecutionSettings:
    """Run-wide settings: concurrency, ordering, and where per-item work runs."""

    def test_parallel_matches_sequential_as_multiset(self):
        pipeline = _tokenized().hash(options={"assign": "h"})
        sequential = list(pipeline)
        parallel = list(pipeline.with_execution(concurrency=4))
        assert len(parallel) == len(sequential) == 3
        assert _by_content(parallel) == _by_content(sequential)

    def test_ordered_preserves_source_order(self):
        pipeline = _tokenized().hash(options={"assign": "h"})
        sequential = list(pipeline)
        ordered = list(pipeline.with_execution(concurrency=4, ordered=True))
        assert ordered == sequential

    @pytest.mark.parametrize("executor", ["inline", "thread", "process"])
    def test_every_executor_produces_the_same_items(self, executor):
        pipeline = Pipeline(source=SRC).hash(options={"assign": "h"})
        executed = list(pipeline.with_execution(executor=executor))
        assert _by_content(executed) == _by_content(pipeline)

    def test_no_settings_preserve_source_order(self):
        pipeline = Pipeline(source=SRC).hash(options={"assign": "h"})
        assert [item["content"] for item in pipeline] == ["a", "b", "c"]

    def test_inline_executor_preserves_source_order(self):
        pipeline = Pipeline(source=SRC).hash(options={"assign": "h"})
        inline = pipeline.with_execution(executor="inline", concurrency=4)
        assert [item["content"] for item in inline] == ["a", "b", "c"]

    def test_auto_with_a_limit_matches_sequential_as_multiset(self):
        pipeline = Pipeline(source=SRC).hash(options={"assign": "h"})
        parallel = list(pipeline.with_execution(concurrency=4))
        assert _by_content(parallel) == _by_content(pipeline)


class TestEnvironmentBinding:
    def test_with_context_derives_without_changing_the_original(self):
        context = Context(inputs={"limit": 5})
        base = Pipeline.from_module("fetch")
        pipeline = base.with_context(context)
        assert pipeline.context is context
        assert base.context is None
        assert pipeline.sort().context is context

    def test_with_resource_extends_the_bound_context(self):
        def open_db():
            yield "conn"

        context = Context(inputs={"limit": 5})
        base = Pipeline.from_module("fetch").with_context(context)
        pipeline = base.with_resource("db", open_db)
        assert pipeline.context is not None
        assert pipeline.context.inputs == context.inputs
        assert sorted(pipeline.context.resources) == ["db"]
        assert dict(context.resources) == {}

    def test_with_resource_rejects_factory_options_on_a_resource(self):
        def open_db():
            yield "conn"

        pipeline = Pipeline.from_module("fetch").with_resource("db", open_db)
        assert pipeline.context is not None
        resource = pipeline.context.resources["db"]

        with pytest.raises(TypeError):
            pipeline.with_resource(  # pyright: ignore[reportCallIssue]
                "other",
                resource,
                lazy=True,  # pyright: ignore[reportArgumentType]
            )

    def test_bound_resource_reaches_the_module(self, reader):
        def open_db():
            yield "conn"

        pipeline = Pipeline(_reader_workflow()).with_resource("primary", open_db)
        assert list(pipeline) == [{"got": "conn"}]

    @skipif_issync
    @async_test
    async def test_bound_resource_reaches_the_module_async(self, reader):
        def open_db():
            yield "conn"

        pipeline = Pipeline(_reader_workflow()).with_context(
            Context().with_resource("primary", open_db)
        )
        assert [item async for item in pipeline] == [{"got": "conn"}]
