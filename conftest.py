"""Shared pytest fixtures and collection hooks for the Riko test suite."""

import doctest
import gc
import importlib.util
import os
import re
from logging import getLogger

import pytest

from riko.bado._backend import issync
from riko.base._config import ASYNC_DOCTEST_MARKERS
from riko.base._logging import LOGGER_NAME
from riko.base._paths import PACKAGE_DIR, ROOT_DIR, TESTS_DIR
from riko.parsing.documents import IS_LXML
from riko.runtime._pubsub import reset_pubsub
from riko.runtime._registrations import temporary_registrations
from riko.runtime._workflow_resolver import register_workflow_store

pytest_plugins = [
    "pytester",
    "tests._hash_seeds",
    "tests._resources",
    "tests._timeouts",
]

_EXAMPLE_DIRS = (PACKAGE_DIR / "modules", PACKAGE_DIR / "rss")
# usage examples may drop a started stream; the test tiers keep leaks strict
QUIET_LEAKS = pytest.mark.filterwarnings("ignore::ResourceWarning")
WORKFLOW_DIR = TESTS_DIR / "workflows"
RUN_CALL = re.compile(r"(?<!def )(?<![\w.])run\(")


def pytest_configure(config: pytest.Config) -> None:
    # Subprocesses (console scripts, examples) would otherwise import riko through the
    # venv's editable install, which points at whichever checkout installed it.
    paths = [str(ROOT_DIR), os.environ.get("PYTHONPATH")]
    os.environ["PYTHONPATH"] = os.pathsep.join(path for path in paths if path)
    # Test bounds are measured without asyncio debug mode, which slows every task.
    os.environ.pop("PYTHONASYNCIODEBUG", None)


@pytest.fixture(autouse=True)
def workflow_store():
    # Core ships no workflow stores; the suite registers its own package of stored
    # workflows plus the directory of workflow documents.
    with temporary_registrations():
        register_workflow_store(package="tests.pyworkflows", directory=WORKFLOW_DIR)
        yield


def _extra_missing(*modules: str) -> list[str]:
    return [m for m in modules if importlib.util.find_spec(m) is None]


@pytest.fixture(autouse=True)
def reset_pubsub_state():
    reset_pubsub()
    yield
    reset_pubsub()


@pytest.fixture
def riko_level():
    level = getLogger(LOGGER_NAME).level
    yield
    getLogger(LOGGER_NAME).setLevel(level)


def _skip_coroutine_runs(item: pytest.DoctestItem) -> None:
    # Without the async backend `run` is a no-op that prints nothing, so skip just
    # those examples and keep the rest of the doctest (often a whole .rst file).
    for example in item.dtest.examples:
        if RUN_CALL.search(example.source):
            example.options[doctest.SKIP] = True


def pytest_runtest_teardown(item: pytest.Item) -> None:
    # collect a quieted example's cyclic garbage while its filter still applies
    if QUIET_LEAKS.mark in item.own_markers:
        gc.collect(0)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
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

        if not isinstance(item, pytest.DoctestItem):
            continue

        name = item.name.lower()

        if any(map(item.path.is_relative_to, _EXAMPLE_DIRS)):
            item.add_marker(QUIET_LEAKS)

        if issync and any(marker in name for marker in ASYNC_DOCTEST_MARKERS):
            item.add_marker(skip_async)
        elif not IS_LXML and "xpathfetchpage" in name:
            item.add_marker(skip_lxml)
        elif issync:
            _skip_coroutine_runs(item)
