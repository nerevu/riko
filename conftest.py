"""Shared pytest fixtures and collection hooks for the Riko test suite."""

from __future__ import annotations

import doctest
import gc
import importlib.util
import os
import re
from asyncio.base_events import BaseEventLoop
from logging import WARNING, getLogger
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING
from weakref import ref

import pytest

from riko.bado._backend import is_sync
from riko.base._config import ASYNC_DOCTEST_MARKERS
from riko.base._logging import LOGGER_NAME
from riko.base._paths import PACKAGE_DIR, ROOT_DIR, TESTS_DIR
from riko.parsing import documents
from riko.parsing.documents import IS_LXML
from riko.runtime._pubsub import reset_pubsub
from riko.runtime._registrations import temporary_registrations
from riko.runtime._workflow_resolver import register_workflow_store
from tests import run_python

if TYPE_CHECKING:
    from collections.abc import Generator
    from types import AsyncGeneratorType

_EXAMPLE_DIRS = (PACKAGE_DIR / "modules", PACKAGE_DIR / "rss")
_FINALIZER_HOOK = "_asyncgen_finalizer_hook"
_FIRSTITER_HOOK = "_asyncgen_firstiter_hook"
_LEAK_MSG = "was finalized by the event loop instead of being closed"
# usage examples may drop a started stream; the test tiers keep leaks strict
QUIET_LEAKS = pytest.mark.filterwarnings("ignore::ResourceWarning")
WORKFLOW_DIR = TESTS_DIR / "workflows"
RUN_CALL = re.compile(r"(?<!def )(?<![\w.])run\(")

pytest_plugins = [
    "pytester",
    "tests._hash_seeds",
    "tests._resources",
    "tests._timeouts",
]


def pytest_configure(config: pytest.Config) -> None:
    # Subprocesses (console scripts, examples) would otherwise import riko through the
    # venv's editable install, which points at whichever checkout installed it.
    paths = [str(ROOT_DIR), os.environ.get("PYTHONPATH")]
    os.environ["PYTHONPATH"] = os.pathsep.join(path for path in paths if path)
    # Test bounds are measured without asyncio debug mode, which slows every task.
    os.environ.pop("PYTHONASYNCIODEBUG", None)


def pytest_sessionstart(session: pytest.Session) -> None:
    # A script outside the checkout must import this checkout, as a console script
    # would; checked once, by the controller, rather than as a subject test.
    if not hasattr(session.config, "workerinput"):
        with TemporaryDirectory() as directory:
            done = run_python("-c", "import riko; print(riko.__file__)", cwd=directory)

        imported = done.stdout.strip()
        expected = str(ROOT_DIR / "riko" / "__init__.py")

        if imported != expected:
            msg = f"subprocesses import riko from {imported}, not {expected}"
            raise pytest.UsageError(msg)


@pytest.fixture(autouse=True)
def workflow_store():
    # Core ships no workflow stores; the suite registers its own package of stored
    # workflows plus the directory of workflow documents.
    with temporary_registrations():
        register_workflow_store(package="tests.pyworkflows", directory=WORKFLOW_DIR)
        yield


def _describe_leak(agen: AsyncGeneratorType[object, object]) -> str:
    code = agen.ag_code
    path = Path(code.co_filename).relative_to(ROOT_DIR)
    where = f"{path}:{code.co_firstlineno}"
    return f"{agen.__qualname__} ({where}) {_LEAK_MSG}"


@pytest.fixture(autouse=True)
def no_leaked_async_generators(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
):
    """
    Fails a test whose riko async generator is left for the event loop to finalize.

    Every async generator riko creates must be closed by whatever owns it. One that is
    abandoned while suspended reaches the loop's finalizer hook, which this fixture
    wraps on every loop the test starts, the portal loops included. Garbage is only
    collected when a riko async generator the test started is still suspended, and a
    quieted example records its leaks without failing.
    """
    leaked: list[str] = []
    started: list[ref[AsyncGeneratorType[object, object]]] = []
    first_iter = getattr(BaseEventLoop, _FIRSTITER_HOOK)
    finalize = getattr(BaseEventLoop, _FINALIZER_HOOK)

    def is_riko(agen: AsyncGeneratorType[object, object]) -> bool:
        return Path(agen.ag_code.co_filename).is_relative_to(PACKAGE_DIR)

    def track(loop: BaseEventLoop, agen: AsyncGeneratorType[object, object]) -> None:
        if is_riko(agen):
            started.append(ref(agen))

        first_iter(loop, agen)

    def record(loop: BaseEventLoop, agen: AsyncGeneratorType[object, object]) -> None:
        if is_riko(agen):
            leaked.append(_describe_leak(agen))

        finalize(loop, agen)

    monkeypatch.setattr(BaseEventLoop, _FIRSTITER_HOOK, track)
    monkeypatch.setattr(BaseEventLoop, _FINALIZER_HOOK, record)
    yield

    if any((agen := r()) is not None and agen.ag_frame is not None for r in started):
        gc.collect()

    if leaked and QUIET_LEAKS.mark not in request.node.own_markers:
        pytest.fail("\n".join(leaked), pytrace=False)


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


@pytest.fixture
def riko_warnings(
    caplog: pytest.LogCaptureFixture,
) -> Generator[pytest.LogCaptureFixture]:
    """Captures the riko logger's warnings for the whole test."""
    with caplog.at_level(WARNING, logger=LOGGER_NAME):
        yield caplog


@pytest.fixture
def streamed_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """Streams every streamable JSON source, whatever its size, for the whole test."""
    monkeypatch.setattr(documents, "STREAMING_THRESHOLD", 0)


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
    skip_docutils = pytest.mark.skip(reason="docutils not installed")
    docutils_missing = _extra_missing("docutils")

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

        if is_sync and any(marker in name for marker in ASYNC_DOCTEST_MARKERS):
            item.add_marker(skip_async)
        elif not IS_LXML and "xpathfetchpage" in name:
            item.add_marker(skip_lxml)
        elif docutils_missing and "_lint_rst" in name:
            item.add_marker(skip_docutils)
        elif is_sync:
            _skip_coroutine_runs(item)
