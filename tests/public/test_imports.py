# vim: sw=4:ts=4:expandtab
"""
Public-contract tests for the API boundary.

``riko`` define the stable application API. ``riko.ext`` defines the extension-author
API. ``riko.bado`` is a supported async-runtime namespace; the BADO subset below is
promoted into the stable application surface.

These tests exercise public imports rather than implementation details.
"""

from importlib import import_module
from importlib.resources import files
from types import BuiltinFunctionType, FunctionType

import pytest

import riko
import riko.bado
import riko.base.exceptions
import riko.ext
import riko.modules
import riko.modules._names
import riko.runtime._codegen
import riko.runtime._migrate
import riko.runtime._resolver
import riko.runtime._workflows
import riko.runtime.collections
import riko.types
from riko.base._api_surface import (
    BADO,
    COLLECTIONS,
    COMPILE,
    EXTENSION,
    MODULES,
    PRIVATE_RESOLUTION,
    ROOT_EXCEPTIONS,
    STABLE,
    TYPES,
)

SURFACE_MODULES = (
    riko.bado,
    riko.runtime.collections,
    riko.runtime._codegen,
    riko.runtime._migrate,
    riko.ext,
    riko.modules,
    riko.base.exceptions,
    riko,
    riko.types,
)
PARTIAL_SURFACES = (
    (riko.modules.__all__ + riko.modules._names.__all__, MODULES),
    (riko.base.exceptions.__all__, ROOT_EXCEPTIONS),
)
CONF_TYPES = riko.types.modules.__all__


CODEGEN = (COMPILE & {"compile_workflow"}) | {"RAW_CONFS", "render_value"}

EQUAL_SURFACES = (
    (riko.bado, BADO),
    (riko.runtime.collections, COLLECTIONS),
    (riko.runtime._codegen, CODEGEN),
    (riko.runtime._migrate, {"parse_dag", "migrate_v1_to_v2"}),
    (riko.ext, EXTENSION),
    (riko, STABLE),
    (riko.types, TYPES),
)


def id_func(val):
    if hasattr(val, "__name__"):
        return val.__name__
    else:
        return "vs-set"


@pytest.mark.smoke
def test_package_ships_py_typed():
    assert files("riko").joinpath("py.typed").is_file()


@pytest.mark.smoke
@pytest.mark.parametrize(("module", "surface"), EQUAL_SURFACES, ids=id_func)
def test_equal_surface_matches_expected(module, surface):
    assert sorted(set(module.__all__)) == sorted(surface)


@pytest.mark.parametrize(("names", "surface"), PARTIAL_SURFACES, ids=id_func)
def test_partial_surface_matches_expected(names, surface):
    assert surface.issubset(names)
    assert not any(name.startswith("_") for name in names)


def test_normal_module_confs_are_public():
    assert "FetchConf" in CONF_TYPES
    assert "RegexConf" in CONF_TYPES
    assert "ItemBuilderConf" in CONF_TYPES


def test_raw_module_confs_are_private():
    leaked = sorted(
        name for name in CONF_TYPES if name.endswith(("RawConf", "RawRule"))
    )
    assert not leaked, f"Raw module confs leaked into riko.types.modules: {leaked}"


def test_module_metadas_are_same():
    assert riko.ext.ModuleMetadata is riko.types.modules.ModuleMetadata


@pytest.mark.parametrize(("module", "surface"), [(riko, STABLE), (riko.ext, EXTENSION)])
def test_stable_names_importable(module, surface):
    """Every declared stable names actually resolves on ``riko``."""
    assert all(hasattr(module, name) for name in surface)


def test_bado_reexports_are_same_object():
    mismatches = sorted(
        name
        for name in riko.bado.__all__
        if getattr(riko, name) is not getattr(riko.bado, name)
    )
    assert not mismatches, f"Bado reexports differ from riko: {mismatches}"


def test_exception_reexports_are_same_object():
    mismatches = sorted(
        name
        for name in ROOT_EXCEPTIONS
        if getattr(riko, name) is not getattr(riko.base.exceptions, name)
    )
    assert not mismatches, f"Exception reexports differ from riko: {mismatches}"


PUBLIC_EXTENSION_MODULES = (
    "riko.ext.codegen",
    "riko.ext.config",
    "riko.ext.decorators",
    "riko.ext.protocols",
    "riko.ext.registry",
)
RESOLUTION_MODULES = (riko.runtime._resolver, riko.runtime._workflows)


def test_private_resolution_names_exist():
    """Every declared private resolution name is defined by a resolution module."""
    missing = sorted(
        name
        for name in PRIVATE_RESOLUTION
        if not any(hasattr(module, name) for module in RESOLUTION_MODULES)
    )
    assert not missing, f"Declared resolution internals do not exist: {missing}"


@pytest.mark.parametrize(
    "module",
    [*SURFACE_MODULES, *map(import_module, PUBLIC_EXTENSION_MODULES)],
    ids=lambda module: module.__name__,
)
def test_no_accidental_internal_exports(module):
    """Private resolution internals are neither exported nor reachable publicly."""
    exported = PRIVATE_RESOLUTION.intersection(getattr(module, "__all__", ()))
    reachable = {name for name in PRIVATE_RESOLUTION if hasattr(module, name)}
    leaked = sorted(exported | reachable)
    assert not leaked, f"Private resolution internals exposed: {leaked}"


@pytest.mark.parametrize("module", RESOLUTION_MODULES, ids=lambda m: m.__name__)
def test_resolution_internals_have_no_public_path(module):
    """Resolution internals live only behind ``_``-prefixed modules."""
    package, _, private_name = module.__name__.rpartition(".")
    public_path = f"{package}.{private_name.lstrip('_')}"
    assert private_name.startswith("_")

    with pytest.raises(ModuleNotFoundError):
        import_module(public_path)


def test_no_leaked_public_functions():
    """
    No bare function leaks into the top-level namespace outside ``__all__``.

    Scoped to *functions* on purpose: classes and constants (e.g. ``Context``,
    ``ENCODING``, ``objectify``) are intentionally importable while absent from
    ``__all__``, so this guards callables rather than the whole attribute surface
    (that surface is pinned by ``test_equal_surface_matches_expected``).
    """
    leaked = sorted(
        name
        for name, val in vars(riko).items()
        if not (name.startswith("_") or name in STABLE)
        and isinstance(val, (FunctionType, BuiltinFunctionType))
    )
    assert not leaked, f"Top-level functions leaked outside STABLE: {leaked}"


def test_stable_and_extension_do_not_intersect():
    common = STABLE & EXTENSION
    assert not common, f"Stable and extension surfaces intersect: {common}"


def test_all_has_no_duplicates():
    duplicates = {
        module.__name__: sorted(
            {name for name in module.__all__ if module.__all__.count(name) > 1}
        )
        for module in SURFACE_MODULES
        if len(module.__all__) != len(set(module.__all__))
    }
    assert not duplicates, f"Duplicate __all__ entries: {duplicates}"
