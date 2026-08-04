# vim: sw=4:ts=4:expandtab
"""
Public-contract tests for the Phase 1 API boundary (docs/P1_CHECKLIST.md).

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
    "export",
    "list_modules",
    "list_targets",
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

DEMOTED = {"Objectify", "objectify", "listize", "get_path", "get_abspath", "replacer"}


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


@pytest.mark.parametrize("name", sorted(DEMOTED))
def test_demoted_names_importable_but_not_public(name):
    assert hasattr(riko, name)
    assert name not in riko.__all__


def test_no_private_names_in_public_all():
    leaked = [n for n in (*riko.__all__, *riko.ext.__all__) if n.startswith("_")]
    assert leaked == []


def test_no_leaked_public_functions():
    """
    No non-``__all__`` function is publicly reachable on ``riko`` except
    the P1 re-export shims (removed at Wnext) and the bare ``overload`` decorator.
    """
    allowed = set(riko.__all__) | DEMOTED | {"overload"}
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
