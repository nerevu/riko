# vim: sw=4:ts=4:expandtab
"""Provides pipelines and sources shared by the sync and async lifecycle tests."""

from __future__ import annotations

from riko.definitions._workflow import Workflow
from riko.runtime._pipeline import Pipeline
from riko.types._compiler import DagModule, PipeDag
from riko.types.modules import ConfArg, FetchRawConf, ItemBuilderConf

_BUILDER_CONF = ItemBuilderConf({"attrs": [{"key": "content", "value": "a,b,c"}]})
LIFECYCLE_SRC = [{"content": "x"}, {"content": "y"}]


def boom():
    raise RuntimeError("boom")
    yield  # pragma: no cover


def tokenized_letters() -> Pipeline:
    """Builds a three-item token stream (``a``, ``b``, ``c``)."""
    source = Pipeline.from_module("itembuilder", conf=_BUILDER_CONF)
    return source.tokenizer(options={"emit": True})


def _fetch_node(index: int, url: str) -> DagModule:
    """Builds one fetch module entry for the fan-in ``PipeDag``."""
    conf = FetchRawConf({"url": ConfArg(type="url", value=url)})
    return DagModule(id=f"f{index}", type="fetch", conf=conf)


def fanned_in_fetches(*urls: str) -> Pipeline:
    """Builds a pipeline whose single union node merges one fetch per url."""
    fetches = [_fetch_node(index, url) for index, url in enumerate(urls)]
    ports = ["in" if index == 0 else f"in:{index}" for index in range(len(urls))]
    wires = [[f"f{index}", "u", port] for index, port in enumerate(ports)]
    union = DagModule(id="u", type="union")
    dag = PipeDag(modules=[*fetches, union], wires=wires)
    return Pipeline(Workflow.parse(dag))
