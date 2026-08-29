# vim: sw=4:ts=4:expandtab
"""
Public-contract tests for the API boundary.

A developer must be able to tell stable / extension / private from the import
path alone. These are black-box tests: they import, they never reach inside.
"""

import types
from importlib import import_module
from operator import attrgetter

import pytest

import riko
import riko.bado
import riko.context
import riko.ext
import riko.modules

MODULES = (riko, riko.bado, riko.ext, riko.modules)


PRIVATE_RESOLUTION = {
    "CompositeStore",
    "DirectoryStore",
    "MappingStore",
    "ModuleStore",
    "PackageStore",
    "PipeResolver",
    "PipelineResolver",
    "pipe_resolver",
    "pipeline_resolver",
}

STABLE = {
    "AsyncCollection",
    "AsyncPipe",
    "Context",
    "ExecutionMode",
    "Modules",
    "PipeState",
    "PipelineStateError",
    "Sinks",
    "Sources",
    "SyncCollection",
    "SyncPipe",
    "Targets",
    "Transforms",
    "UnsupportedModuleError",
    "UnsupportedPipelineError",
    "async_read",
    "async_return",
    "async_sleep",
    "async_write",
    "list_modules",
    "backend",
    "build_pipeline",
    "compile_pipe",
    "convert_dag",
    "describe_module",
    "export",
    "extract_dependencies",
    "get_module_metadata",
    "get_path",
    "get_async_temp_file",
    "get_temp_file",
    "isasync",
    "issync",
    "list_targets",
    "parse_pipe_def",
    "run",
}

EXTENSION = {
    "AsyncOperatorWrapper",
    "AsyncProcessorWrapper",
    "AsyncSplitterWrapper",
    "DynamicConf",
    "ModuleDefinition",
    "ModuleMetadata",
    "ModuleName",
    "ModuleNameLike",
    "ModuleRegistry",
    "ModuleSubtype",
    "ModuleType",
    "ModuleWrapper",
    "SyncOperatorWrapper",
    "SyncProcessorWrapper",
    "SyncSplitterWrapper",
    "derive_category",
    "get_conf_type",
    "normalize_module_name",
    "operator",
    "processor",
    "register",
    "splitter",
}


@pytest.mark.smoke
def test_stable_all_is_expected_set():
    assert set(riko.__all__) == STABLE


@pytest.mark.parametrize("name", sorted(STABLE))
def test_stable_names_importable(name):
    assert hasattr(riko, name)


@pytest.mark.smoke
def test_extension_all_is_expected_set():
    assert set(riko.ext.__all__) == EXTENSION


@pytest.mark.parametrize("name", sorted(EXTENSION))
def test_extension_names_importable(name):
    assert hasattr(riko.ext, name)


def test_context_shim_is_same_object():
    assert riko.Context is riko.context.Context


def test_no_private_names_in_public_all():
    assert not any(n.startswith("_") for module in MODULES for n in module.__all__)


def test_no_accidental_internal_exports():
    """Private resolution internals stay out of public namespace exports."""
    public = (n for module in MODULES for n in module.__all__)
    assert PRIVATE_RESOLUTION.isdisjoint(public)


@pytest.mark.parametrize("path", ["riko.ext.resolver", "riko.ext.pipelines"])
def test_resolution_internals_have_no_public_path(path):
    """Resolution internals stay behind ``_``-prefixed modules (§3)."""
    with pytest.raises(ModuleNotFoundError):
        import_module(path)


def test_no_leaked_public_functions():
    """
    No non-``__all__`` function is publicly reachable on ``riko``. The former
    demoted helpers now live in private modules (``riko.paths``/``_objectify``/
    ``_iterutils``/``_strutils``), so the public surface is exactly ``__all__``.
    """
    allowed = set(riko.__all__)
    leaked = sorted(
        name
        for name, val in vars(riko).items()
        if not name.startswith("_")
        and name not in allowed
        and isinstance(val, (types.FunctionType, types.BuiltinFunctionType))
    )
    assert leaked == []


def test_stable_and_extension_do_not_intersect():
    assert STABLE.isdisjoint(EXTENSION)


@pytest.mark.parametrize("module", MODULES, ids=attrgetter("__name__"))
def test_all_has_no_duplicates(module):
    names = module.__all__
    assert len(names) == len(set(names))
