# vim: sw=4:ts=4:expandtab
"""
Tests module discovery, derived metadata, and export target listing.
"""

from collections.abc import Iterator

import pytest

from riko.collections import CONVERSION_FUNCS, list_targets
from riko.modules import ModuleMetadata, list_modules, operator
from riko.modules.count import pipe as count_pipe


def get_metadata(name: str) -> ModuleMetadata:
    modules = list_modules(show_metadata=True)
    return next(module for module in modules if module.name == name)


def test_list_modules_names():
    modules = list_modules()

    assert modules == tuple(sorted(modules))
    assert "count" in modules
    assert "fetch" in modules
    assert "split" in modules


def test_filter_by_type():
    modules = list_modules(type="processor", show_metadata=True)

    assert modules
    assert all(module.type == "processor" for module in modules)


def test_filter_by_supported_subtype():
    aggregators = list_modules(subtype="aggregator")
    composers = list_modules(subtype="composer")

    # count supports both behaviors
    assert "count" in aggregators
    assert "count" in composers

    # aggregate only produces streams
    assert "aggregate" not in aggregators
    assert "aggregate" in composers


def test_filter_by_primary_subtype():
    primary_aggregators = list_modules(subtype="aggregator", primary=True)
    primary_composers = list_modules(subtype="composer", primary=True)

    # count supports composing through count_key, but its default
    # wrapped behavior is aggregator.
    assert "count" in primary_aggregators
    assert "count" not in primary_composers

    assert all(
        module.subtype == "aggregator"
        for module in list_modules(
            subtype="aggregator", primary=True, show_metadata=True
        )
    )


def test_filter_loopable_modules():
    modules = list_modules(loopable=True, show_metadata=True)

    assert modules
    assert all(module.loopable for module in modules)

    assert "fetch" in {module.name for module in modules}
    assert "dateformat" in {module.name for module in modules}
    assert "input" not in {module.name for module in modules}
    assert "count" not in {module.name for module in modules}
    assert "split" not in {module.name for module in modules}


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
    assert list_modules(subtype="source", loopable=False) == ("input",)


def test_filter_non_loopable_processors():
    assert list_modules(type="processor", loopable=False) == ("input",)


def test_type_and_subtype_cannot_be_combined():
    with pytest.raises(ValueError, match="type and subtype cannot be combined"):
        list_modules(type="operator", subtype="composer")


def test_primary_requires_subtype():
    with pytest.raises(ValueError, match="primary=True requires subtype"):
        list_modules(primary=True)


def test_count_metadata():
    metadata = get_metadata("count")

    assert metadata.type == "operator"
    assert metadata.subtype == "aggregator"
    assert metadata.subtypes == {"aggregator", "composer"}
    assert metadata.has_sync
    assert metadata.has_async


def test_processor_metadata():
    source = get_metadata("fetch")
    transformer = get_metadata("dateformat")

    assert source.type == "processor"
    assert source.subtype == "source"
    assert source.subtypes == {"source"}

    assert transformer.type == "processor"
    assert transformer.subtype == "transformer"
    assert transformer.subtypes == {"transformer"}


def test_splitter_metadata():
    metadata = get_metadata("split")

    assert metadata.type == "splitter"
    assert metadata.subtype == "splitter"
    assert metadata.subtypes == {"splitter"}


def test_loopable_metadata():
    # processors are loopable (they transform a single item) ...
    assert get_metadata("dateformat").loopable
    assert get_metadata("itembuilder").loopable

    # ... except input, which prompts for interactive user input
    assert not get_metadata("input").loopable

    # operators and splitters cannot be embedded in a loop
    assert not get_metadata("count").loopable
    assert not get_metadata("split").loopable


def test_operator_metadata_is_derived():
    @operator()
    def value_pipe(*args, **kwargs) -> int:
        return 1

    @operator()
    def mapping_pipe(*args, **kwargs) -> dict[str, int]:
        return {"count": 1}

    @operator()
    def stream_pipe(*args, **kwargs) -> Iterator[dict[str, int]]:
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
    assert list_targets() == tuple(sorted(CONVERSION_FUNCS))
