# vim: sw=4:ts=4:expandtab
"""
Public-contract tests for the Phase 1 API boundary (docs/P1_CHECKLIST.md).

A developer must be able to tell stable / extension / private from the import
path alone. These are black-box tests: they import, they never reach inside.
"""

import pytest

import riko
import riko.api
import riko.context
import riko.ext

STABLE = {
    "AsyncCollection",
    "AsyncPipe",
    "Context",
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
    "ModuleMetadata",
    "ModuleSubtype",
    "ModuleType",
    "ModuleWrapper",
    "SyncOperatorWrapper",
    "SyncProcessorWrapper",
    "SyncSplitterWrapper",
    "operator",
    "processor",
    "splitter",
}

DEMOTED = {"Objectify", "Objconf", "objectify", "listize", "get_path"}


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


def test_stable_and_extension_are_disjoint():
    assert STABLE.isdisjoint(EXTENSION)
