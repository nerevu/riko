# vim: sw=4:ts=4:expandtab
"""
Public-contract tests for the API boundary.

A developer must be able to tell stable / extension / private from the import
path alone. These are black-box tests: they import, they never reach inside.
"""

import types

import pytest

import riko
import riko.api
import riko.context
import riko.ext

STABLE = {
    "AsyncCollection",
    "AsyncPipe",
    "Context",
    "ExecutionMode",
    "PipeState",
    "PipelineStateError",
    "SyncCollection",
    "SyncPipe",
    "UnsupportedModuleError",
    "UnsupportedPipelineError",
    "async_return",
    "async_sleep",
    "backend",
    "build_pipeline",
    "compile_pipe",
    "convert_dag",
    "export",
    "extract_dependencies",
    "get_module_metadata",
    "get_path",
    "isasync",
    "issync",
    "list_modules",
    "list_targets",
    "parse_pipe_def",
    "run",
}

EXTENSION = {
    "AsyncOperatorWrapper",
    "AsyncProcessorWrapper",
    "AsyncSplitterWrapper",
    "DynamicConf",
    "ModuleMetadata",
    "ModuleSubtype",
    "ModuleType",
    "ModuleWrapper",
    "SyncOperatorWrapper",
    "SyncProcessorWrapper",
    "SyncSplitterWrapper",
    "get_conf_type",
    "operator",
    "processor",
    "splitter",
}


def test_stable_all_matches_api():
    assert set(riko.__all__) == set(riko.api.__all__)


def test_stable_all_is_expected_set():
    assert set(riko.__all__) == STABLE


@pytest.mark.parametrize("name", sorted(STABLE))
def test_stable_names_importable(name):
    assert hasattr(riko, name)


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
