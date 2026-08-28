# vim: sw=4:ts=4:expandtab
"""
Public-contract tests for the API boundary.

A developer must be able to tell stable / extension / private from the import
path alone. These are black-box tests: they import, they never reach inside.
"""

import types
from importlib import import_module

import pytest

import riko
import riko.api
import riko.context
import riko.ext
import riko.modules

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


def test_stable_all_matches_api():
    assert set(riko.__all__) == set(riko.api.__all__)


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
    leaked = [n for n in (*riko.__all__, *riko.ext.__all__) if n.startswith("_")]
    assert leaked == []


def test_no_accidental_internal_exports():
    """
    ``API_SURFACE.md`` §3 PRIVATE names stay out of every public ``__all__``.

    ``riko.ext`` is a public namespace, so resolution internals are private by
    *declaration* rather than by path. Nothing stops them being re-exported by accident.
    """
    public = {
        *riko.__all__,
        *riko.api.__all__,
        *riko.ext.__all__,
        *riko.modules.__all__,
    }
    assert PRIVATE_RESOLUTION & public == set()


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


def test_stable_and_extension_are_disjoint():
    assert STABLE.isdisjoint(EXTENSION)


@pytest.mark.parametrize(
    "module", [riko, riko.api, riko.ext, riko.modules], ids=lambda m: m.__name__
)
def test_all_has_no_duplicates(module):
    names = module.__all__
    assert len(names) == len(set(names))
