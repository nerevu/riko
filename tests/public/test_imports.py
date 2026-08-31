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
import riko.collections
import riko.compile
import riko.exceptions
import riko.ext
import riko.modules
import riko.modules._names
import riko.types
from riko._api_surface import (
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
    riko.collections,
    riko.compile,
    riko.ext,
    riko.modules,
    riko.exceptions,
    riko,
    riko.types,
)
PARTIAL_SURFACES = (
    (riko.modules.__all__ + riko.modules._names.__all__, MODULES),
    (riko.exceptions.__all__, ROOT_EXCEPTIONS),
)
CONF_TYPES = riko.types.modules.__all__


EQUAL_SURFACES = (
    (riko.bado, BADO),
    (riko.collections, COLLECTIONS),
    (riko.compile, COMPILE),
    (riko.ext, EXTENSION),
    (riko, STABLE),
    (riko.types, TYPES),
)


@pytest.mark.smoke
@pytest.mark.parametrize(
    ("module", "surface"), EQUAL_SURFACES, ids=lambda m: getattr(m, "__name__", m)
)
def test_equal_surface_matches_expected(module, surface):
    assert set(module.__all__) == surface


@pytest.mark.parametrize(
    ("names", "surface"), PARTIAL_SURFACES, ids=lambda m: getattr(m, "__name__", m)
)
def test_partial_surface_matches_expected(names, surface):
    assert surface.issubset(names)


def test_normal_module_confs_are_public():
    assert "FetchConf" in CONF_TYPES
    assert "RegexConf" in CONF_TYPES
    assert "ItemBuilderConf" in CONF_TYPES


@pytest.mark.parametrize("name", CONF_TYPES)
def test_raw_module_confs_are_private(name):
    assert not name.endswith(("RawConf", "RawRule"))


def test_module_metadas_are_same():
    assert riko.ext.ModuleMetadata is riko.types.modules.ModuleMetadata


@pytest.mark.parametrize("name", sorted(STABLE))
def test_stable_names_importable(name):
    assert hasattr(riko, name)


@pytest.mark.parametrize("name", sorted(EXTENSION))
def test_extension_names_importable(name):
    assert hasattr(riko.ext, name)


@pytest.mark.parametrize("name", riko.bado.__all__)
def test_bado_reexports_are_same_object(name):
    assert getattr(riko, name) is getattr(riko.bado, name)


@pytest.mark.parametrize("name", sorted(ROOT_EXCEPTIONS))
def test_exception_reexports_are_same_object(name):
    assert getattr(riko, name) is getattr(riko.exceptions, name)


@pytest.mark.parametrize("module", SURFACE_MODULES)
def test_no_private_names_in_public_all(module):
    assert not any(n.startswith("_") for n in module.__all__)


@pytest.mark.parametrize("module", SURFACE_MODULES)
def test_no_accidental_internal_exports(module):
    """Private resolution internals stay out of public namespace exports."""
    assert PRIVATE_RESOLUTION.isdisjoint(module.__all__)


@pytest.mark.parametrize("path", ["riko.ext.resolver", "riko.ext.pipelines"])
def test_resolution_internals_have_no_public_path(path):
    """Resolution internals stay behind ``_``-prefixed modules (§3)."""
    with pytest.raises(ModuleNotFoundError):
        import_module(path)


@pytest.mark.parametrize(("name", "val"), vars(riko).items())
def test_no_leaked_public_functions(name, val):
    """The top-level function surface is exactly the functions in ``__all__``."""
    if not (name.startswith("_") or name in STABLE):
        assert not isinstance(val, (FunctionType, BuiltinFunctionType))


def test_stable_and_extension_do_not_intersect():
    assert STABLE.isdisjoint(EXTENSION)


@pytest.mark.parametrize("module", SURFACE_MODULES)
def test_all_has_no_duplicates(module):
    names = module.__all__
    assert len(names) == len(set(names))
