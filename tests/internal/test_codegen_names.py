# vim: sw=4:ts=4:expandtab
"""
Tests generated module-name discovery.

Covers user type classification, enum name generation, collisions, and
generated module-name and module-id output. Generated files must match the
current module catalog.
"""

import dataclasses
from typing import get_args

import pytest

from riko.ext.codegen import (
    NameEntry,
    enum_member_name,
    gen_catalog_entries,
    generate_module_ids,
    generate_module_names,
)
from riko.ext.names import derive_category
from riko.modules import list_modules
from riko.modules._metadata import gen_module_catalog
from riko.paths import PACKAGE_DIR
from riko.types._module_ids import LoopableModuleId, ModuleId
from riko.types.modules import ModuleCategory

_NAMES = PACKAGE_DIR / "modules" / "_names.py"
_MODULE_IDS = PACKAGE_DIR / "types" / "_module_ids.py"

_SOURCES = {
    "csv",
    "feedautodiscovery",
    "fetch",
    "fetchdata",
    "fetchpage",
    "fetchsitefeed",
    "fetchtable",
    "fetchtext",
    "forever",
    "input",
    "itembuilder",
    "rssitembuilder",
    "urlbuilder",
    "xpathfetchpage",
}


_SINKS = {"write"}


@pytest.fixture
def categories() -> dict[str, ModuleCategory]:
    return {md.name: derive_category(md) for md in gen_module_catalog()}


def test_taxonomy_partition_matches_golden(categories):
    buckets: dict[str, set[str]] = {"source": set(), "sink": set(), "transform": set()}
    for name, category in categories.items():
        buckets[category].add(name)

    assert buckets["source"] == _SOURCES
    assert buckets["sink"] == _SINKS
    assert buckets["transform"] == set(categories) - _SOURCES - _SINKS


def test_provider_override_wins():
    md = next(iter(gen_module_catalog()))
    assert derive_category(md, provider="microsoft") == "microsoft"
    assert derive_category(md, provider="microsoft", override="custom") == "custom"


def test_sink_name_is_classified_as_sink():
    md = next(md for md in gen_module_catalog() if md.name == "fetch")
    renamed = dataclasses.replace(md, name="write")
    assert derive_category(renamed) == "sink"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("fetch", "FETCH"),
        ("fetch-page", "FETCH_PAGE"),
        ("microsoft.autopilot.ensure", "MICROSOFT_AUTOPILOT_ENSURE"),
        ("a--b..c", "A_B_C"),
        ("3m", "_3M"),
    ],
)
def test_enum_member_name(name, expected):
    assert enum_member_name(name, override=None) == expected


def test_enum_member_name_override():
    assert enum_member_name("fetch", override="grab") == "GRAB"


def test_generated_names_match():
    entries = gen_catalog_entries()
    name_lines = _NAMES.read_text().splitlines()
    generated_lines = generate_module_names(*entries).splitlines()

    for actual, expected in zip(name_lines, generated_lines, strict=True):
        assert actual == expected


def test_generation_is_order_independent():
    entries = list(gen_catalog_entries())
    assert generate_module_names(*entries) == generate_module_names(*reversed(entries))


def test_generated_module_ids_match():
    assert _MODULE_IDS.read_text() == generate_module_ids()


def test_loopable_ids_match_catalog():
    assert set(get_args(LoopableModuleId)) == set(list_modules(loopable=True))
    assert set(get_args(LoopableModuleId)) <= set(get_args(ModuleId))


def test_member_collision_fails_with_diagnostic():
    entries = [
        NameEntry(name="my.mod", category="transform"),
        NameEntry(name="my-mod", category="transform"),
    ]

    with pytest.raises(ValueError, match="enum_name") as excinfo:
        generate_module_names(*entries)

    assert "'my.mod'" in str(excinfo.value)
    assert "'my-mod'" in str(excinfo.value)


def test_enum_name_override_resolves_collision():
    entries = [
        NameEntry(name="my.mod", category="transform"),
        NameEntry(name="my-mod", category="transform", enum_name="my_mod_alt"),
    ]
    src = generate_module_names(*entries)
    assert "MY_MOD_ALT" in src


def test_provider_namespace_flattens():
    entries = [
        NameEntry(name="fetch", category="source"),
        NameEntry(name="microsoft.autopilot.ensure", category="microsoft"),
    ]
    src = generate_module_names(*entries)
    assert "class Microsoft(ModuleName):" in src
    assert 'MICROSOFT_AUTOPILOT_ENSURE = "microsoft.autopilot.ensure"' in src
    assert (
        "    MICROSOFT_AUTOPILOT_ENSURE = Microsoft.MICROSOFT_AUTOPILOT_ENSURE" in src
    )
