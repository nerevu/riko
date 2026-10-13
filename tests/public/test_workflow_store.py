# vim: sw=4:ts=4:expandtab
"""Tests that workflow documents in a workflow store resolve as stored workflows."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from riko.bado.itertools import as_async
from riko.base.exceptions import UnsupportedWorkflowError
from riko.definitions._context import Context
from riko.runtime._pipeline import Pipeline
from riko.runtime._resolver import dispatcher
from riko.runtime._workflows import register_workflow_store
from riko.types._enums import ExecutionMode
from riko.types.modules import ItemBuilderConf, StrconcatRawConf
from tests import async_test

if TYPE_CHECKING:
    from pathlib import Path

PARENT = [{"title": "hi"}]
EXCLAIMED = [{"title": "hi", "strconcat": "hi!"}]


def write_document(directory: Path, name: str, suffix: str) -> None:
    conf = StrconcatRawConf(
        {
            "part": [
                {"subkey": "title", "type": "text"},
                {"type": "text", "value": suffix},
            ]
        }
    )
    pipeline = Pipeline.from_module("strconcat", conf=conf)
    path = directory / f"{name}.json"
    path.write_bytes(pipeline.workflow.serialize())


@pytest.fixture
def documents(tmp_path: Path) -> Path:
    write_document(tmp_path, "pipe_exclaim", "!")
    write_document(tmp_path, "pipe_shout", "?")
    register_workflow_store(directory=tmp_path, replace=True)
    return tmp_path


def build_outer() -> Pipeline:
    conf = ItemBuilderConf({"attrs": [{"key": "title", "value": "hi"}]})
    source = Pipeline.from_module("itembuilder", conf=conf)
    return source.pipe(
        "loop",
        options={"count": "all", "emit": True},
        embed={"name": "pipe:exclaim", "conf": {}},
    )


@pytest.mark.usefixtures("documents")
class TestWorkflowDocumentResolution:
    def test_document_runs_as_pipeline(self):
        pipeline = Pipeline.from_module("pipe_exclaim")
        assert list(PARENT | pipeline) == EXCLAIMED

    def test_document_exposes_both_interfaces(self):
        interfaces = dispatcher.require_interfaces("pipe_exclaim")
        assert interfaces == frozenset({"pipe", "async_pipe"})

    def test_document_embeds_in_a_loop(self):
        assert list(build_outer()) == EXCLAIMED

    def test_document_describes_dependencies(self):
        context = Context(ExecutionMode.DESCRIBE_DEPENDENCIES)
        pipe = dispatcher.require("pipe_exclaim")
        assert pipe(context=context) == ["strconcat"]

    def test_module_wins_over_document(self):
        pipeline = Pipeline.from_module("pipe_shout")
        items = list(PARENT | pipeline)
        assert items == EXCLAIMED

    def test_missing_name_still_raises(self):
        with pytest.raises(UnsupportedWorkflowError):
            dispatcher.require("pipe_missing")

    @async_test
    async def test_document_runs_async(self):
        pipe = dispatcher.require("pipe_exclaim", is_async=True)
        items = [item async for item in pipe(as_async(PARENT))]
        assert items == EXCLAIMED

    @async_test
    async def test_document_runs_as_async_pipeline(self):
        pipeline = Pipeline.from_module("pipe_exclaim")
        assert [item async for item in PARENT | pipeline] == EXCLAIMED
        assert [item async for item in build_outer()] == EXCLAIMED
