# vim: sw=4:ts=4:expandtab
"""
Tests module discovery, derived metadata, and export target listing.
"""

from collections.abc import Iterator
from typing import Any

import pytest

from riko import get_module_metadata
from riko.cast import CastType
from riko.collections import CONVERSION_FUNCS, list_targets
from riko.context import Context
from riko.modules import describe_module, list_modules, operator
from riko.modules.count import pipe as count_pipe
from riko.modules.input import pipe as input_pipe
from riko.types.modules import InputConf


def test_input_test_flag_scoped_to_test_context(monkeypatch):
    """
    The auto-wired context.test skips the input prompt only in a test
    context. A non-test context (test=False) still prompts, so the flag can
    never silently suppress prompting outside of tests.
    """
    monkeypatch.setattr("builtins.input", lambda *args: "typed")
    conf = InputConf({"prompt": "?", "default": "def", "type": CastType.TEXT})

    assert next(input_pipe(conf=conf, context=Context(test=True))) == "def"
    assert next(input_pipe(conf=conf, context=Context(test=False))) == "typed"
    assert next(input_pipe(conf=conf)) == "typed"


def test_filter_non_loopable_modules():
    modules = list_modules(loopable=False, show_metadata=True)

    assert modules
    assert all(not module.loopable for module in modules)

    names = {module.name for module in modules}
    assert "input" in names
    assert "count" in names
    assert "split" in names
    assert "dateformat" not in names


def test_filter_non_loopable_sources():
    assert list_modules(subtype="source", loopable=False) == ["input"]


def test_filter_non_loopable_processors():
    assert list_modules(type="processor", loopable=False) == ["input"]


def test_type_and_subtype_cannot_be_combined():
    with pytest.raises(ValueError, match="type and subtype cannot be combined"):
        list_modules(type="operator", subtype="composer")


def test_primary_requires_subtype():
    with pytest.raises(ValueError, match="primary=True requires subtype"):
        list_modules(primary=True)


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


def test_count_default_and_emitted_subtypes():
    items = ({"content": value} for value in range(3))
    assert next(count_pipe(items)) == {"count": 3}

    items = ({"content": value} for value in range(3))
    assert next(count_pipe(items, emit=True)) == 3


def test_list_targets():
    assert list_targets() == sorted(CONVERSION_FUNCS)


def test_describe_module_reraises_nested_dependency_error(monkeypatch):
    def boom(target):
        raise ModuleNotFoundError("No module named 'phantom_dep'", name="phantom_dep")

    monkeypatch.setattr("riko._importutils.import_module", boom)

    with pytest.raises(ModuleNotFoundError, match="phantom_dep"):
        describe_module("hash")
