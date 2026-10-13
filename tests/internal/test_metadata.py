# vim: sw=4:ts=4:expandtab
"""
Test derived module metadata and return-shape inference.

This covers ``get_module_metadata`` classification and ``@operator`` inference.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from riko.ext import operator, processor
from riko.modules._metadata import get_module_metadata
from riko.runtime._workflows import mark_subpipe
from riko.types._wrappers import WRAPPER_META, stamp_wrapper_meta

if TYPE_CHECKING:
    from collections.abc import Iterator

    from riko.types._streams import Item


def test_operator_metadata():
    metadata = get_module_metadata("count", strict=True)
    assert metadata.type == "operator"
    assert metadata.subtype == "aggregator"
    assert metadata.subtypes == {"aggregator", "composer"}
    assert metadata.has_sync
    assert metadata.has_async


def test_processor_metadata():
    source = get_module_metadata("fetch", strict=True)
    transformer = get_module_metadata("dateformat", strict=True)

    assert source.type == "processor"
    assert source.subtype == "source"
    assert source.subtypes == {"source"}

    assert transformer.type == "processor"
    assert transformer.subtype == "transformer"
    assert transformer.subtypes == {"transformer"}


def test_splitter_metadata():
    metadata = get_module_metadata("split", strict=True)
    assert metadata.type == "splitter"
    assert metadata.subtype == "splitter"
    assert metadata.subtypes == {"splitter"}


def test_loopable_metadata():
    # processors are loopable (they transform a single item) ...
    assert get_module_metadata("dateformat", strict=True).loopable
    assert get_module_metadata("itembuilder", strict=True).loopable

    # ... except input, which prompts for interactive user input
    assert not get_module_metadata("input", strict=True).loopable

    # operators and splitters cannot be embedded in a loop
    assert not get_module_metadata("count", strict=True).loopable
    assert not get_module_metadata("split", strict=True).loopable


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


def test_unknown_module_metadata_is_none():
    assert get_module_metadata("not_a_builtin_module") is None


def test_unknown_module_metadata_raises_when_strict():
    with pytest.raises(ValueError, match="has no metadata"):
        get_module_metadata("not_a_builtin_module", strict=True)


def _carries_wrapper_meta(func: object) -> bool:
    return all(hasattr(func, attr) for attr in WRAPPER_META)


def test_stamped_function_carries_wrapper_meta():
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


def test_marked_subpipe_carries_wrapper_meta():
    def pipe(item=None, **kwargs):
        return iter([])

    async def async_pipe(item=None, **kwargs):
        yield {}

    def other(item=None, **kwargs):
        return iter([])

    sync_subpipe = mark_subpipe(pipe)
    async_subpipe = mark_subpipe(async_pipe)

    assert _carries_wrapper_meta(sync_subpipe)
    assert _carries_wrapper_meta(async_subpipe)
    assert not sync_subpipe.isasync
    assert async_subpipe.isasync
    assert mark_subpipe(other, isasync=True).isasync


def test_decorated_wrappers_carry_wrapper_meta():
    def shout(item: Item, *args, **kwargs) -> str:
        return str(item.get("content", "")).upper()

    def total(*args: Any, **kwargs: object) -> int:
        return 1

    assert _carries_wrapper_meta(processor()(shout))
    assert _carries_wrapper_meta(processor(isasync=True)(shout))
    assert _carries_wrapper_meta(operator()(total))
