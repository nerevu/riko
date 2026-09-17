# vim: sw=4:ts=4:expandtab
"""
Public-contract tests for the API boundary.

``riko`` define the stable application API. ``riko.ext`` defines the extension-author
API. ``riko.bado`` is a supported async-runtime namespace; the BADO subset below is
promoted into the stable application surface.

These tests exercise public imports rather than implementation details.
"""

from importlib import import_module
from types import BuiltinFunctionType, FunctionType

import pytest

import riko
import riko.bado
import riko.base.exceptions
import riko.ext
import riko.modules
import riko.modules._names
import riko.runtime._compile
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
    riko.runtime._compile,
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


EQUAL_SURFACES = (
    (riko.bado, BADO),
    (riko.runtime.collections, COLLECTIONS),
    (riko.runtime._compile, COMPILE),
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


def test_no_accidental_internal_exports():
    """Private resolution internals stay out of public namespace exports."""
    violations = {
        module.__name__: sorted(PRIVATE_RESOLUTION.intersection(module.__all__))
        for module in SURFACE_MODULES
        if PRIVATE_RESOLUTION.intersection(module.__all__)
    }
    assert not violations, f"Private resolution internals exported: {violations}"


@pytest.mark.parametrize("path", ["riko.ext.resolver", "riko.ext.pipelines"])
def test_resolution_internals_have_no_public_path(path):
    """Resolution internals stay behind ``_``-prefixed modules (§3)."""
    with pytest.raises(ModuleNotFoundError):
        import_module(path)


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
