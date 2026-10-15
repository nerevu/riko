"""Shared pytest fixtures and collection hooks for the Riko test suite."""

import doctest
import importlib.util
import re

import pytest

from riko.bado._backend import issync
from riko.base._paths import ROOT_DIR
from riko.parsing.documents import IS_LXML
from riko.runtime._pubsub import reset_pubsub
from riko.runtime._workflow_resolver import (
    register_workflow_store,
    reset_workflow_resolver,
)

pytest_plugins = ["pytester", "tests._timeouts"]

WORKFLOW_DIR = ROOT_DIR / "tests" / "workflows"
RUN_CALL = re.compile(r"(?<![\w.])run\(")


@pytest.fixture(autouse=True)
def workflow_store():
    # Core ships no workflow stores; the suite registers its own package of stored
    # workflows plus the directory of workflow documents.
    reset_workflow_resolver()
    register_workflow_store(package="tests.pyworkflows", directory=WORKFLOW_DIR)
    yield
    reset_workflow_resolver()


def _extra_missing(*modules: str) -> list[str]:
    return [m for m in modules if importlib.util.find_spec(m) is None]


@pytest.fixture(autouse=True)
def reset_pubsub_state():
    reset_pubsub()
    yield
    reset_pubsub()


def _skip_coroutine_runs(item) -> None:
    # Without the async backend `run` is a no-op that prints nothing, so skip just
    # those examples and keep the rest of the doctest (often a whole .rst file).
    for example in item.dtest.examples:
        if RUN_CALL.search(example.source):
            example.options[doctest.SKIP] = True


def pytest_collection_modifyitems(items):
    skip_async = pytest.mark.skip(reason="async support not available")
    skip_lxml = pytest.mark.skip(reason="lxml not installed")

    perf_missing = _extra_missing("lxml", "ijson", "fastfeedparser")
    finance_missing = _extra_missing("csv2ofx")
    skip_perf = pytest.mark.skip(reason=f"perf extra not installed: {perf_missing}")
    skip_finance = pytest.mark.skip(
        reason=f"finance extra not installed: {finance_missing}"
    )

    for item in items:
        keywords = item.keywords

        if perf_missing and "perf" in keywords:
            item.add_marker(skip_perf)

        if finance_missing and "finance" in keywords:
            item.add_marker(skip_finance)

        if not hasattr(item, "dtest"):
            continue

        name = item.name.lower()

        if issync and ("async" in name or "bado" in name):
            item.add_marker(skip_async)
        elif not IS_LXML and "xpathfetchpage" in name:
            item.add_marker(skip_lxml)
        elif issync:
            _skip_coroutine_runs(item)
