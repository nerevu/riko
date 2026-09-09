# vim: sw=4:ts=4:expandtab
"""
Derived module metadata: ``get_module_metadata`` classification and the
``@operator`` return-shape subtype inference.
"""

from collections.abc import Iterator
from typing import Any

from riko.ext import operator
from riko.modules._metadata import get_module_metadata


def test_operator_metadata():
    metadata = get_module_metadata("count")
    assert metadata.type == "operator"
    assert metadata.subtype == "aggregator"
    assert metadata.subtypes == {"aggregator", "composer"}
    assert metadata.has_sync
    assert metadata.has_async


def test_processor_metadata():
    source = get_module_metadata("fetch")
    transformer = get_module_metadata("dateformat")

    assert source.type == "processor"
    assert source.subtype == "source"
    assert source.subtypes == {"source"}

    assert transformer.type == "processor"
    assert transformer.subtype == "transformer"
    assert transformer.subtypes == {"transformer"}


def test_splitter_metadata():
    metadata = get_module_metadata("split")
    assert metadata.type == "splitter"
    assert metadata.subtype == "splitter"
    assert metadata.subtypes == {"splitter"}


def test_loopable_metadata():
    # processors are loopable (they transform a single item) ...
    assert get_module_metadata("dateformat").loopable
    assert get_module_metadata("itembuilder").loopable

    # ... except input, which prompts for interactive user input
    assert not get_module_metadata("input").loopable

    # operators and splitters cannot be embedded in a loop
    assert not get_module_metadata("count").loopable
    assert not get_module_metadata("split").loopable


def test_operator_metadata_is_derived():
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
