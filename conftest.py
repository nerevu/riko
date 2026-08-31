import importlib.util
from doctest import ELLIPSIS

import pytest

from riko._pubsub import reset_pubsub
from riko.bado._backend import issync
from riko.ext._pipelines import DirectoryStore, PackageStore, pipeline_resolver
from riko.parsers import IS_LXML
from riko.paths import ROOT_DIR

try:
    from sybil import Sybil
    from sybil.parsers.markdown import PythonCodeBlockParser
except ImportError:
    pass
else:
    from importlib import import_module

    import riko._api_surface as surface

    def _seed_api_surface(namespace: dict) -> None:
        import riko  # noqa: PLC0415

        import_module("riko.bado")
        import_module("riko.context")

        names = dir(surface)
        namespace["riko"] = riko
        namespace.update({n: getattr(surface, n) for n in names if n.isupper()})

    parser = PythonCodeBlockParser(doctest_optionflags=ELLIPSIS)
    pytest_collect_file = Sybil(
        parsers=[parser], patterns=["API_SURFACE.md"], setup=_seed_api_surface
    ).pytest()


PIPELINE_DIR = ROOT_DIR / "tests" / "pipelines"

# The core compiler ships no named-pipeline locations; the suite supplies its
# own generated-package store + JSON-definition directory (formerly hardcoded as
# ``tests.pypipelines`` / ``tests/pipelines`` inside ``riko.compile``).
store = PackageStore("tests.pypipelines")
pipeline_resolver.configure(store=store, definitions=DirectoryStore(PIPELINE_DIR))


def _extra_missing(*modules: str) -> list[str]:
    return [m for m in modules if importlib.util.find_spec(m) is None]


@pytest.fixture(autouse=True)
def reset_pubsub_state():
    reset_pubsub()
    yield
    reset_pubsub()


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

        name = item.name

        if issync and ("async" in name):
            item.add_marker(skip_async)
        elif not IS_LXML and "xpathfetchpage" in name:
            item.add_marker(skip_lxml)
